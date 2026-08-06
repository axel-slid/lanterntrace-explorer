const { timelineSnapshots: snapshots, surveillanceSites: sentinelSites, corridors: transportCorridors, citySearch: placeSearch } = window.LanternTraceData;
const observationBundle = window.LanternTraceObservations || { metadata: {}, observations: [] };
const observationPoints = observationBundle.observations;
const observationMetadata = observationBundle.metadata;
const previewObservationPoints = observationPoints.filter((_, index) => index % 20 === 0);

const layers = { heatmap: true, reports: true, front: true, uncertainty: true, corridors: true, sites: false };
let snapshotIndex = snapshots.length - 1;
let map;
let playing = false;
let timer;
let animationLastFrame = 0;
let lastReportStep = -1;
let pendingSliderFrame;
let pendingSliderReportTimer;
let lastSliderReportUpdate = 0;
let isTimelineScrubbing = false;
let corridorAnimationFrame;
let corridorAnimationLast = 0;
let usingReportPreview = false;
const timelineOverviewZoom = 4.75;

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const darkStyle = {
  version: 8,
  sources: {
    cartoBase: {
      type: 'raster',
      tiles: ['https://a.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png', 'https://b.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors © CARTO'
    },
    cartoLabels: {
      type: 'raster',
      tiles: ['https://a.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png', 'https://b.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors © CARTO'
    }
  },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#06172e' } },
    { id: 'carto-base', type: 'raster', source: 'cartoBase', paint: { 'raster-opacity': 0.82, 'raster-saturation': -0.25, 'raster-contrast': 0.42, 'raster-brightness-min': 0.02, 'raster-brightness-max': 0.5 } },
    { id: 'carto-labels', type: 'raster', source: 'cartoLabels', paint: { 'raster-opacity': 0.76, 'raster-saturation': -0.2, 'raster-contrast': 0.3, 'raster-brightness-min': 0.05, 'raster-brightness-max': 0.62 } }
  ]
};

function geojsonFeature(type, coordinates, properties = {}) {
  return { type: 'Feature', geometry: { type, coordinates }, properties };
}

function pointAlongCorridor(line, progress) {
  const segments = line.slice(1).map((point, index) => {
    const start = line[index];
    const latitude = (start[1] + point[1]) / 2;
    const dx = (point[0] - start[0]) * Math.cos(latitude * Math.PI / 180);
    const dy = point[1] - start[1];
    return { start, end: point, length: Math.hypot(dx, dy), angle: Math.atan2(dy, dx) * 180 / Math.PI };
  });
  const totalLength = segments.reduce((sum, segment) => sum + segment.length, 0);
  let distance = progress * totalLength;
  for (const segment of segments) {
    if (distance <= segment.length) {
      const blend = segment.length ? distance / segment.length : 0;
      return {
        coordinates: [segment.start[0] + (segment.end[0] - segment.start[0]) * blend, segment.start[1] + (segment.end[1] - segment.start[1]) * blend],
        angle: segment.angle
      };
    }
    distance -= segment.length;
  }
  return { coordinates: line.at(-1), angle: segments.at(-1)?.angle || 0 };
}

function corridorFlowData(phase = 0) {
  const directionGlyphs = ['→', '↗', '↑', '↖', '←', '↙', '↓', '↘'];
  const features = [];
  transportCorridors.forEach((line, corridorIndex) => {
    for (let arrowIndex = 0; arrowIndex < 3; arrowIndex += 1) {
      const position = pointAlongCorridor(line, (phase + arrowIndex / 3 + corridorIndex * 0.07) % 1);
      const directionIndex = Math.round((((position.angle % 360) + 360) % 360) / 45) % 8;
      features.push(geojsonFeature('Point', position.coordinates, { corridor: corridorIndex + 1, arrow: directionGlyphs[directionIndex] }));
    }
  });
  return { type: 'FeatureCollection', features };
}

function startCorridorAnimation() {
  cancelAnimationFrame(corridorAnimationFrame);
  const animate = (timestamp) => {
    if (layers.corridors && timestamp - corridorAnimationLast >= (playing || isTimelineScrubbing ? 33 : 90)) {
      const source = map?.getSource('lt-corridor-flow');
      if (source) source.setData(corridorFlowData((timestamp / 10500) % 1));
      corridorAnimationLast = timestamp;
    }
    corridorAnimationFrame = requestAnimationFrame(animate);
  };
  corridorAnimationFrame = requestAnimationFrame(animate);
}

function addCorridorArrowImage() {
  if (map.hasImage('lt-flow-arrow')) return;
  const size = 32;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext('2d');
  context.beginPath();
  context.moveTo(4, 8);
  context.lineTo(27, 16);
  context.lineTo(4, 24);
  context.lineTo(10, 16);
  context.closePath();
  context.fillStyle = '#d9f280';
  context.shadowColor = 'rgba(90, 160, 85, .55)';
  context.shadowBlur = 4;
  context.fill();
  map.addImage('lt-flow-arrow', { width: size, height: size, data: context.getImageData(0, 0, size, size).data }, { pixelRatio: 2 });
}

const monthIndex = new Map(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].map((month, index) => [month, index]));

function snapshotCutoff(snapshot = snapshots[snapshotIndex]) {
  const [year, month] = String(snapshot.period || `${snapshot.year} Dec`).split(' ');
  return Date.UTC(Number(year), (monthIndex.get(month) ?? 11) + 1, 0, 23, 59, 59, 999);
}

function reportCountAt(cutoff) {
  let low = 0;
  let high = observationPoints.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    const timestamp = Date.parse(`${observationPoints[middle][2]}T23:59:59Z`) || 0;
    if (timestamp <= cutoff) low = middle + 1;
    else high = middle;
  }
  return low;
}

function reportData(points = observationPoints) {
  return {
    type: 'FeatureCollection',
    features: points.map(([lng, lat, date, key, state, locality, basis, datasetKey, license, occurrenceID]) => geojsonFeature('Point', [lng, lat], {
      observedAt: Date.parse(`${date}T23:59:59Z`) || 0,
      date,
      key,
      state,
      locality,
      basis,
      datasetKey,
      license,
      occurrenceID
    }))
  };
}

const envelopeCellSize = 0.45;

function convexHull(points) {
  const unique = [...new Map(points.map(([x, y]) => [`${x},${y}`, [x, y]])).values()].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (unique.length <= 2) return unique;
  const cross = (origin, a, b) => (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0]);
  const lower = [];
  for (const point of unique) {
    while (lower.length >= 2 && cross(lower.at(-2), lower.at(-1), point) <= 0) lower.pop();
    lower.push(point);
  }
  const upper = [];
  for (const point of [...unique].reverse()) {
    while (upper.length >= 2 && cross(upper.at(-2), upper.at(-1), point) <= 0) upper.pop();
    upper.push(point);
  }
  const hull = lower.slice(0, -1).concat(upper.slice(0, -1));
  hull.push(hull[0]);
  return hull;
}

function occurrenceEnvelope(occupiedCells) {
  const unvisited = new Set(occupiedCells.keys());
  const components = [];
  while (unvisited.size) {
    const start = unvisited.values().next().value;
    const queue = [start];
    const component = [];
    unvisited.delete(start);
    while (queue.length) {
      const key = queue.pop();
      const [x, y] = key.split(':').map(Number);
      component.push([x, y]);
      for (let dx = -2; dx <= 2; dx += 1) {
        for (let dy = -2; dy <= 2; dy += 1) {
          if (!dx && !dy) continue;
          const neighbor = `${x + dx}:${y + dy}`;
          if (unvisited.delete(neighbor)) queue.push(neighbor);
        }
      }
    }
    const corners = component.flatMap(([x, y]) => {
      const west = x * envelopeCellSize - 180;
      const south = y * envelopeCellSize - 90;
      return [[west, south], [west + envelopeCellSize, south], [west + envelopeCellSize, south + envelopeCellSize], [west, south + envelopeCellSize]];
    });
    const ring = convexHull(corners);
    if (ring.length >= 4) {
      const reportWeight = component.reduce((total, [x, y]) => total + (occupiedCells.get(`${x}:${y}`) || 0), 0);
      components.push({ ring, reportWeight, cellCount: component.length });
    }
  }
  const dominant = components.sort((a, b) => b.reportWeight - a.reportWeight || b.cellCount - a.cellCount)[0];
  return { type: 'MultiPolygon', coordinates: dominant ? [[dominant.ring]] : [] };
}

function transformEnvelope(geometry, yearsAhead, uncertainty = false) {
  const growth = 1 + yearsAhead * (uncertainty ? 0.075 : 0.04);
  const drift = [yearsAhead * 0.32, yearsAhead * 0.13];
  return {
    type: 'MultiPolygon',
    coordinates: geometry.coordinates.map(([ring]) => {
      const points = ring.slice(0, -1);
      const center = points.reduce((sum, [lng, lat]) => [sum[0] + lng / points.length, sum[1] + lat / points.length], [0, 0]);
      return [ring.map(([lng, lat]) => [center[0] + (lng - center[0]) * growth + drift[0], center[1] + (lat - center[1]) * growth + drift[1]])];
    })
  };
}

function applyOccurrenceDerivedEnvelopes() {
  const occupiedCells = new Map();
  let observationIndex = 0;
  let latestObservedGeometry = { type: 'MultiPolygon', coordinates: [] };
  for (const snapshot of snapshots) {
    const cutoff = snapshotCutoff(snapshot);
    while (observationIndex < observationPoints.length) {
      const point = observationPoints[observationIndex];
      const timestamp = Date.parse(`${point[2]}T23:59:59Z`) || 0;
      if (timestamp > cutoff) break;
      const cellX = Math.floor((point[0] + 180) / envelopeCellSize);
      const cellY = Math.floor((point[1] + 90) / envelopeCellSize);
      const key = `${cellX}:${cellY}`;
      occupiedCells.set(key, (occupiedCells.get(key) || 0) + 1);
      observationIndex += 1;
    }
    latestObservedGeometry = occurrenceEnvelope(occupiedCells);
    snapshot.frontGeometry = latestObservedGeometry;
    snapshot.cells = String(occupiedCells.size);
    if (!snapshot.isProjection) {
      snapshot.uncertaintyGeometry = { type: 'MultiPolygon', coordinates: [] };
      snapshot.confidence = '—';
      snapshot.leadingEdge = 'Report-derived occurrence footprint';
    } else {
      const yearsAhead = snapshot.projectionHorizonYears || 0;
      snapshot.uncertaintyGeometry = transformEnvelope(latestObservedGeometry, yearsAhead, true);
      snapshot.leadingEdge = 'Observed core with separate prospective envelope';
    }
  }
}

function snapshotGeometryFeature(snapshot, key, step = snapshotIndex) {
  const geometryKey = `${key}Geometry`;
  const smoothKey = `${key}SmoothGeometry`;
  const geometry = snapshot[smoothKey] || (snapshot[smoothKey] = smoothBoundaryGeometry(snapshot[geometryKey]));
  return geometry
    ? { type: 'Feature', geometry, properties: { year: snapshot.year, step, isProjection: Boolean(snapshot.isProjection) } }
    : geojsonFeature('Polygon', [snapshot[key]], { year: snapshot.year, step });
}

function smoothClosedRing(ring, iterations = 2) {
  if (!ring || ring.length < 4) return ring;
  let points = ring.slice(0, -1);
  for (let pass = 0; pass < iterations; pass += 1) {
    const rounded = [];
    for (let index = 0; index < points.length; index += 1) {
      const current = points[index];
      const next = points[(index + 1) % points.length];
      rounded.push(
        [current[0] * 0.75 + next[0] * 0.25, current[1] * 0.75 + next[1] * 0.25],
        [current[0] * 0.25 + next[0] * 0.75, current[1] * 0.25 + next[1] * 0.75]
      );
    }
    points = rounded;
  }
  return [...points, points[0]];
}

function smoothBoundaryGeometry(geometry) {
  if (!geometry) return geometry;
  if (geometry.type === 'Polygon') return { ...geometry, coordinates: geometry.coordinates.map((ring) => smoothClosedRing(ring)) };
  if (geometry.type === 'MultiPolygon') return { ...geometry, coordinates: geometry.coordinates.map((polygon) => polygon.map((ring) => smoothClosedRing(ring))) };
  return geometry;
}

applyOccurrenceDerivedEnvelopes();

function sourceData() {
  return {
    front: { type: 'FeatureCollection', features: snapshots.map((snapshot, step) => snapshotGeometryFeature(snapshot, 'front', step)) },
    uncertainty: { type: 'FeatureCollection', features: snapshots.map((snapshot, step) => snapshotGeometryFeature(snapshot, 'uncertainty', step)) },
    reports: reportData(),
    corridors: { type: 'FeatureCollection', features: transportCorridors.map((line, i) => geojsonFeature('LineString', line, { corridor: i + 1 })) },
    sites: { type: 'FeatureCollection', features: sentinelSites.map(([lng, lat, label]) => geojsonFeature('Point', [lng, lat], { label })) }
  };
}

function addMapLayers() {
  const data = sourceData();
  const observationFilter = ['<=', ['get', 'observedAt'], snapshotCutoff()];
  map.addSource('lt-front', { type: 'geojson', data: { type: 'FeatureCollection', features: [data.front.features[snapshotIndex]] } });
  map.addSource('lt-uncertainty', { type: 'geojson', data: { type: 'FeatureCollection', features: [data.uncertainty.features[snapshotIndex]] } });
  map.addSource('lt-reports', { type: 'geojson', data: data.reports });
  map.addSource('lt-reports-preview', { type: 'geojson', data: reportData(previewObservationPoints) });
  map.addSource('lt-corridors', { type: 'geojson', data: data.corridors });
  map.addSource('lt-corridor-flow', { type: 'geojson', data: corridorFlowData() });
  map.addSource('lt-sites', { type: 'geojson', data: data.sites });

  map.addLayer({ id: 'lt-heatmap', type: 'heatmap', source: 'lt-reports', maxzoom: 6.5, filter: observationFilter, paint: {
    'heatmap-weight': ['interpolate', ['linear'], ['zoom'], 0, 0.5, 8, 1.4],
    'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 0, 0.2, 8, 0.66],
    'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 2, 7, 6, 12, 10, 19],
    'heatmap-opacity': 0.38,
    'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, 'rgba(9, 41, 43, 0)', 0.12, 'rgba(20, 112, 102, .18)', 0.32, 'rgba(32, 169, 125, .34)', 0.58, 'rgba(81, 211, 148, .48)', 0.82, 'rgba(171, 237, 116, .58)', 1, 'rgba(210, 247, 151, .68)']
  } });
  map.addLayer({ id: 'lt-heatmap-preview', type: 'heatmap', source: 'lt-reports-preview', maxzoom: 6.5, filter: observationFilter, layout: { visibility: 'none' }, paint: {
    'heatmap-weight': ['interpolate', ['linear'], ['zoom'], 0, 0.5, 8, 1.4],
    'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 0, 0.32, 8, 0.9],
    'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 2, 7, 6, 12, 10, 19],
    'heatmap-opacity': 0.42,
    'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, 'rgba(9, 41, 43, 0)', 0.12, 'rgba(20, 112, 102, .18)', 0.32, 'rgba(32, 169, 125, .34)', 0.58, 'rgba(81, 211, 148, .48)', 0.82, 'rgba(171, 237, 116, .58)', 1, 'rgba(210, 247, 151, .68)']
  } });
  map.addLayer({ id: 'lt-uncertainty-fill', type: 'fill', source: 'lt-uncertainty', paint: { 'fill-color': '#2e8f78', 'fill-opacity': 0.22, 'fill-outline-color': '#69dcae' } });
  map.addLayer({ id: 'lt-uncertainty-line', type: 'line', source: 'lt-uncertainty', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#64d9ab', 'line-width': 2, 'line-opacity': 0.58, 'line-blur': 0.25 } });
  map.addLayer({ id: 'lt-front-fill', type: 'fill', source: 'lt-front', paint: { 'fill-color': '#229b77', 'fill-opacity': 0.2 } });
  map.addLayer({ id: 'lt-front-line', type: 'line', source: 'lt-front', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#79efb4', 'line-width': 3, 'line-opacity': 0.9, 'line-blur': 0.12 } });
  map.addLayer({ id: 'lt-front-glow', type: 'line', source: 'lt-front', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#3be0a0', 'line-width': 7, 'line-opacity': 0.05, 'line-blur': 4 } });
  map.addLayer({ id: 'lt-corridor-glow', type: 'line', source: 'lt-corridors', paint: { 'line-color': '#b6de6c', 'line-width': ['interpolate', ['linear'], ['zoom'], 2, 8, 7, 12], 'line-opacity': 0.1, 'line-blur': 5 } });
  map.addLayer({ id: 'lt-corridors', type: 'line', source: 'lt-corridors', paint: { 'line-color': '#b7df77', 'line-width': ['interpolate', ['linear'], ['zoom'], 2, 1.3, 7, 2.6], 'line-opacity': 0.7 } });
  map.addLayer({ id: 'lt-corridor-arrows', type: 'symbol', source: 'lt-corridor-flow', layout: { 'text-field': ['get', 'arrow'], 'text-size': ['interpolate', ['linear'], ['zoom'], 2, 11, 7, 16], 'text-allow-overlap': true, 'text-ignore-placement': true }, paint: { 'text-color': '#d9f280', 'text-halo-color': '#173926', 'text-halo-width': 1.1, 'text-opacity': 0.92 } });
  map.addLayer({ id: 'lt-reports', type: 'circle', source: 'lt-reports', minzoom: 5.5, filter: observationFilter, paint: { 'circle-color': '#74d7ad', 'circle-radius': ['interpolate', ['linear'], ['zoom'], 5.5, 1.5, 8, 2.6, 11, 4.4], 'circle-stroke-color': '#bdebd2', 'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 5.5, 0.35, 9, 0.7], 'circle-opacity': ['interpolate', ['linear'], ['zoom'], 5.5, 0.48, 9, 0.72, 11, 0.84] } });
  map.addLayer({ id: 'lt-report-hit', type: 'circle', source: 'lt-reports', minzoom: 5.5, filter: observationFilter, paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 5.5, 6, 8, 8, 11, 11], 'circle-opacity': 0.01, 'circle-color': '#ffffff' } });
  map.addLayer({ id: 'lt-reports-preview', type: 'circle', source: 'lt-reports-preview', filter: observationFilter, layout: { visibility: 'none' }, paint: { 'circle-color': '#9be7c5', 'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 0.65, 4.75, 1.2, 8, 3, 11, 4.8], 'circle-stroke-color': '#d0f4e1', 'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 2, 0, 4.75, 0.25, 8, 0.55], 'circle-opacity': ['interpolate', ['linear'], ['zoom'], 2, 0.34, 4.75, 0.62, 8, 0.8] } });
  map.addLayer({ id: 'lt-sites', type: 'circle', source: 'lt-sites', paint: { 'circle-color': '#c8ff79', 'circle-radius': 6, 'circle-stroke-color': '#e8ffd2', 'circle-stroke-width': 1.5, 'circle-opacity': 0.9 } });

  map.on('click', 'lt-report-hit', async (event) => {
    const feature = event.features[0];
    const properties = feature.properties;
    const popup = document.createElement('div');
    popup.className = 'report-popup';

    const kicker = document.createElement('span');
    kicker.className = 'report-kicker';
    kicker.textContent = 'PUBLIC OCCURRENCE REPORT';
    const title = document.createElement('b');
    title.textContent = [properties.locality, properties.state].filter(Boolean).join(', ') || properties.state || 'Mapped occurrence';
    popup.append(kicker, title);

    const mediaFrame = document.createElement('div');
    mediaFrame.className = 'report-media loading';
    mediaFrame.textContent = 'Loading observation image…';
    popup.append(mediaFrame);

    const rows = [
      ['Observed', properties.date || 'Date unavailable'],
      ['Record type', String(properties.basis || 'occurrence').replaceAll('_', ' ').toLowerCase()],
      ['Coordinates', `${feature.geometry.coordinates[1].toFixed(5)}, ${feature.geometry.coordinates[0].toFixed(5)}`],
      ['GBIF ID', properties.key]
    ];
    const details = document.createElement('div');
    details.className = 'report-details';
    rows.forEach(([label, value]) => {
      const row = document.createElement('div');
      const term = document.createElement('span');
      const description = document.createElement('strong');
      term.textContent = label;
      description.textContent = value;
      row.append(term, description);
      details.append(row);
    });
    popup.append(details);

    const actions = document.createElement('div');
    actions.className = 'report-actions';
    const gbifLink = document.createElement('a');
    gbifLink.href = `https://www.gbif.org/occurrence/${properties.key}`;
    gbifLink.target = '_blank';
    gbifLink.rel = 'noopener noreferrer';
    gbifLink.textContent = 'VIEW GBIF RECORD ↗';
    actions.append(gbifLink);
    if (/^https?:\/\//.test(properties.occurrenceID || '')) {
      const originalLink = document.createElement('a');
      originalLink.href = properties.occurrenceID;
      originalLink.target = '_blank';
      originalLink.rel = 'noopener noreferrer';
      originalLink.textContent = 'ORIGINAL REPORT ↗';
      actions.append(originalLink);
    }
    popup.append(actions);
    new maplibregl.Popup({ closeButton: true, offset: 12, className: 'lt-popup', maxWidth: '410px' }).setLngLat(feature.geometry.coordinates).setDOMContent(popup).addTo(map);

    try {
      const response = await fetch(`https://api.gbif.org/v1/occurrence/${properties.key}`);
      if (!response.ok) throw new Error(`GBIF media request failed: ${response.status}`);
      const record = await response.json();
      const photo = (record.media || []).find((item) => item.type === 'StillImage' && /^https?:\/\//.test(item.identifier || ''));
      if (!photo) {
        mediaFrame.className = 'report-media empty';
        mediaFrame.textContent = 'No public image is attached to this report.';
      } else {
        const imageLink = document.createElement('a');
        imageLink.href = /^https?:\/\//.test(photo.references || '') ? photo.references : photo.identifier;
        imageLink.target = '_blank';
        imageLink.rel = 'noopener noreferrer';
        const image = document.createElement('img');
        image.src = photo.identifier.replace('/original.', '/medium.');
        image.alt = `Observation image for ${title.textContent}`;
        image.loading = 'lazy';
        imageLink.append(image);
        const credit = document.createElement('span');
        const license = String(photo.license || '').includes('by-nc') ? 'CC BY-NC'
          : String(photo.license || '').includes('/by/') ? 'CC BY'
            : String(photo.license || '').includes('zero') ? 'CC0'
              : 'source license';
        credit.textContent = [photo.creator ? `Photo: ${photo.creator}` : '', license].filter(Boolean).join(' · ');
        mediaFrame.className = 'report-media has-image';
        mediaFrame.replaceChildren(imageLink, credit);
      }
    } catch (error) {
      mediaFrame.className = 'report-media empty';
      mediaFrame.textContent = 'Image unavailable. Open the source report to view its media.';
    }
  });
  map.on('mouseenter', 'lt-report-hit', () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', 'lt-report-hit', () => { map.getCanvas().style.cursor = ''; });
}

function setMapLayerVisibility(layer, visible) {
  const ids = { heatmap: [usingReportPreview ? 'lt-heatmap-preview' : 'lt-heatmap'], reports: [usingReportPreview ? 'lt-reports-preview' : 'lt-reports', ...(usingReportPreview ? [] : ['lt-report-hit'])], front: ['lt-front-fill', 'lt-front-line', 'lt-front-glow'], uncertainty: ['lt-uncertainty-fill', 'lt-uncertainty-line'], corridors: ['lt-corridor-glow', 'lt-corridors', 'lt-corridor-arrows'], sites: ['lt-sites'] };
  if (layer === 'heatmap') [usingReportPreview ? 'lt-heatmap' : 'lt-heatmap-preview'].forEach((id) => { if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', 'none'); });
  if (layer === 'reports') [usingReportPreview ? 'lt-reports' : 'lt-reports-preview', 'lt-report-hit'].forEach((id) => { if (map.getLayer(id) && !ids.reports.includes(id)) map.setLayoutProperty(id, 'visibility', 'none'); });
  (ids[layer] || []).forEach((id) => { if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none'); });
}

function setReportPreviewMode(active) {
  if (usingReportPreview === active || !map?.getLayer('lt-reports-preview')) return;
  usingReportPreview = active;
  setMapLayerVisibility('heatmap', layers.heatmap);
  setMapLayerVisibility('reports', layers.reports);
}

function ensureTimelineOverview() {
  if (!map || map.getZoom() <= timelineOverviewZoom) return;
  map.jumpTo({ zoom: timelineOverviewZoom });
}

function syncLayerControls() {
  $$('[data-layer]').forEach((control) => {
    if (control.tagName === 'BUTTON') control.classList.toggle('on', Boolean(layers[control.dataset.layer]));
    if (control.tagName === 'INPUT') control.checked = Boolean(layers[control.dataset.layer]);
  });
  const activeCount = Object.values(layers).filter(Boolean).length;
  const count = $('.layer-control b');
  if (count) count.textContent = activeCount;
}

function updateSnapshot({ deferReports = false, previewReports = false } = {}) {
  const snapshot = snapshots[snapshotIndex];
  const reportCount = reportCountAt(snapshotCutoff(snapshot));
  $('#timeline-year').textContent = snapshot.period || snapshot.year;
  $('#timeline-phase').textContent = snapshot.isProjection ? 'prospective step' : 'evidence step';
  $('#snapshot-label').textContent = snapshot.label.toUpperCase();
  $('#leading-edge').textContent = snapshot.leadingEdge;
  $('#metric-cells').textContent = snapshot.cells;
  $('#metric-confidence').textContent = snapshot.confidence;
  $('#metric-reports').textContent = reportCount.toLocaleString();
  $('#timeline').value = snapshotIndex;
  $('#timeline-progress').style.width = `${(snapshotIndex / (snapshots.length - 1)) * 100}%`;
  if (map && map.getSource('lt-front')) {
    map.getSource('lt-front').setData({ type: 'FeatureCollection', features: [snapshotGeometryFeature(snapshot, 'front')] });
    map.getSource('lt-uncertainty').setData({ type: 'FeatureCollection', features: [snapshotGeometryFeature(snapshot, 'uncertainty')] });
    const usePreview = playing || previewReports || isTimelineScrubbing;
    if (!deferReports && (usePreview || !playing || lastReportStep < 0)) {
      const reportFilter = ['<=', ['get', 'observedAt'], snapshotCutoff(snapshot)];
      const targetIds = usePreview ? ['lt-heatmap-preview', 'lt-reports-preview'] : ['lt-heatmap', 'lt-reports', 'lt-report-hit'];
      targetIds.forEach((id) => { if (map.getLayer(id)) map.setFilter(id, reportFilter); });
      lastReportStep = snapshotIndex;
    }
  }
}

function initMap() {
  map = new maplibregl.Map({ container: 'map', style: 'https://tiles.openfreemap.org/styles/dark', center: [-76, 38], zoom: 2.65, maxZoom: 15, minZoom: 1.6, attributionControl: false, dragRotate: false });
  map.on('styleimagemissing', ({ id }) => {
    if (!id.startsWith('circle-') || map.hasImage(id)) return;
    const size = 32;
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    const context = canvas.getContext('2d');
    context.beginPath();
    context.arc(size / 2, size / 2, 10, 0, Math.PI * 2);
    context.fillStyle = '#9fb5c9';
    context.fill();
    context.strokeStyle = '#d9e8f1';
    context.lineWidth = 2;
    context.stroke();
    map.addImage(id, { width: size, height: size, data: context.getImageData(0, 0, size, size).data });
  });
  map.on('load', () => {
    map.setProjection({ type: 'globe' });
    map.jumpTo({ center: [-76, 38], zoom: 2.65 });
    tintBaseMapDarkGreen();
    updateGlobeAtmosphere();
    addMapLayers();
    startCorridorAnimation();
    Object.entries(layers).forEach(([layer, visible]) => setMapLayerVisibility(layer, visible));
    syncLayerControls();
    renderTimelineTicks();
    updateSnapshot();
  });
  map.on('resize', updateGlobeAtmosphere);
  map.on('zoom', updateGlobeAtmosphere);
  map.on('zoomend', () => {
    if ((playing || isTimelineScrubbing) && map.getZoom() > timelineOverviewZoom) ensureTimelineOverview();
  });
}

function tintBaseMapDarkGreen() {
  const styleLayers = map.getStyle().layers || [];
  styleLayers.forEach((layer) => {
    const sourceLayer = layer['source-layer'] || '';
    if (layer.type === 'background') {
      map.setPaintProperty(layer.id, 'background-color', '#04110b');
      return;
    }
    if (layer.type === 'fill') {
      const color = sourceLayer === 'water' ? '#061712'
        : sourceLayer === 'landcover' ? '#0b2117'
          : sourceLayer === 'landuse' ? '#0a1e15'
            : sourceLayer === 'building' ? '#0d241b'
              : '#081a12';
      if (map.getPaintProperty(layer.id, 'fill-color') !== undefined) map.setPaintProperty(layer.id, 'fill-color', color);
      if (map.getPaintProperty(layer.id, 'fill-outline-color') !== undefined) map.setPaintProperty(layer.id, 'fill-outline-color', '#173c2b');
      return;
    }
    if (layer.type === 'line') {
      const color = sourceLayer === 'boundary' ? '#285642'
        : sourceLayer === 'waterway' ? '#12372c'
          : '#193629';
      if (map.getPaintProperty(layer.id, 'line-color') !== undefined) map.setPaintProperty(layer.id, 'line-color', color);
      return;
    }
    if (layer.type === 'symbol') {
      if (map.getPaintProperty(layer.id, 'text-color') !== undefined) map.setPaintProperty(layer.id, 'text-color', '#769786');
      if (map.getPaintProperty(layer.id, 'text-halo-color') !== undefined) map.setPaintProperty(layer.id, 'text-halo-color', '#06110c');
    }
  });
}

function updateGlobeAtmosphere() {
  if (!map) return;
  const stage = $('.map-stage');
  const width = stage.clientWidth;
  const height = stage.clientHeight;
  const globeDiameter = (512 * (2 ** map.getZoom())) / Math.PI;
  const contourFit = width / globeDiameter;
  const rimOpacity = stage.classList.contains('globe-mode') ? Math.max(0, Math.min(1, (contourFit - .98) / .08)) : 0;
  stage.style.setProperty('--globe-size', `${globeDiameter}px`);
  stage.style.setProperty('--globe-left', `${(width - globeDiameter) / 2}px`);
  stage.style.setProperty('--globe-top', `${(height - globeDiameter) / 2}px`);
  stage.style.setProperty('--globe-rim-opacity', rimOpacity.toFixed(3));
  stage.classList.toggle('globe-rim-visible', rimOpacity > .01);
}

function createStarfield() {
  const container = $('.starfield');
  const stars = [
    [6, 12, 7, .92], [13, 31, 3, .68], [21, 72, 5, .82], [29, 18, 3, .72], [36, 87, 4, .7],
    [43, 10, 5, .88], [51, 24, 2, .7], [58, 8, 3, .74], [65, 19, 6, .86], [74, 11, 3, .68],
    [83, 23, 5, .82], [92, 14, 3, .88], [97, 37, 4, .7], [89, 71, 6, .82], [78, 88, 3, .75],
    [67, 95, 4, .9], [54, 82, 3, .7], [47, 67, 5, .84], [34, 94, 3, .78], [24, 84, 4, .86],
    [12, 91, 6, .74], [4, 59, 3, .9], [18, 49, 2, .8], [94, 57, 3, .78], [81, 45, 2, .72]
  ];
  let seed = 17;
  for (let index = 0; index < 72; index += 1) {
    seed = (seed * 9301 + 49297) % 233280;
    const x = 3 + (seed / 233280) * 94;
    seed = (seed * 9301 + 49297) % 233280;
    const y = 3 + (seed / 233280) * 94;
    stars.push([x, y, index % 9 === 0 ? 3 : 1.5, index % 4 === 0 ? .9 : .64]);
  }
  stars.forEach(([x, y, size, opacity], index) => {
    const star = document.createElement('i');
    star.className = `star star-${index % 3}`;
    star.style.left = `${x}%`;
    star.style.top = `${y}%`;
    star.style.width = `${size}px`;
    star.style.height = `${size}px`;
    star.style.opacity = opacity;
    star.style.animationDelay = `${(index % 7) * .45}s`;
    container.appendChild(star);
  });
}

function renderTimelineTicks() {
  $('#timeline-step-count').textContent = snapshots.length;
  $('#timeline').max = snapshots.length - 1;
  const years = snapshots.reduce((entries, snapshot, index) => {
    if (!entries.some((entry) => entry.year === snapshot.year)) entries.push({ year: snapshot.year, index, isProjection: Boolean(snapshot.isProjection) });
    return entries;
  }, []);
  $('.timeline-ticks').innerHTML = years.map(({ year, index, isProjection }) => `<span class="year-tick ${isProjection ? 'projection-tick' : ''}" style="left:${(index / (snapshots.length - 1)) * 100}%">${year}</span>`).join('');
  const firstProjection = snapshots.findIndex((snapshot) => snapshot.isProjection);
  const evidenceShare = firstProjection === -1 ? 100 : (firstProjection / snapshots.length) * 100;
  $('.timeline-track').style.setProperty('--evidence-share', `${evidenceShare}%`);
}

function switchSection(section) {
  $$('.section-tab').forEach((button) => button.classList.toggle('active', button.dataset.section === section));
  $$('.topbar-section').forEach((button) => button.classList.toggle('active', button.dataset.section === section));
  ['front', 'evidence', 'actions', 'methods'].forEach((name) => $(`#${name}-panel`).classList.toggle('hidden', name !== section));
}

function setSnapshot(index, options) { snapshotIndex = Math.max(0, Math.min(snapshots.length - 1, index)); updateSnapshot(options); }

function stopPlayback() {
  if (!playing) return;
  playing = false;
  cancelAnimationFrame(timer);
  animationLastFrame = 0;
  $('#timeline-play').textContent = '▶';
}

function togglePlay() {
  playing = !playing;
  $('#timeline-play').textContent = playing ? 'Ⅱ' : '▶';
  cancelAnimationFrame(timer);
  animationLastFrame = 0;
  if (playing) {
    ensureTimelineOverview();
    setReportPreviewMode(true);
    if (snapshotIndex >= snapshots.length - 1) setSnapshot(0, { previewReports: true });
    const animate = (timestamp) => {
      if (!playing) return;
      if (!animationLastFrame) animationLastFrame = timestamp;
      if (timestamp - animationLastFrame >= 33) {
        animationLastFrame += 33;
        if (snapshotIndex >= snapshots.length - 1) {
          playing = false;
          $('#timeline-play').textContent = '▶';
          setReportPreviewMode(false);
          updateSnapshot();
          return;
        }
        setSnapshot(snapshotIndex + 1);
      }
      timer = requestAnimationFrame(animate);
    };
    timer = requestAnimationFrame(animate);
  } else {
    setReportPreviewMode(false);
    updateSnapshot();
  }
}

function toggleSidebar() {
  const shell = $('.app-shell');
  const collapsed = shell.classList.toggle('sidebar-collapsed');
  $$('.menu-button, .topbar-sidebar-icon').forEach((button) => button.setAttribute('aria-expanded', String(!collapsed)));
}

function downloadSnapshot() {
  const snapshot = snapshots[snapshotIndex];
  const payload = { app: 'LanternTrace Explorer', generatedAt: new Date().toISOString(), snapshot, layers, caveat: 'Prototype illustrative synthesis; not field validation.' };
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }));
  link.download = `lanterntrace-front-${snapshot.year}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function searchPlace(value) {
  const key = value.trim().toLowerCase();
  const result = Object.keys(placeSearch).find((name) => name.includes(key) || key.includes(name));
  const results = $('#search-results');
  if (!key) { results.classList.remove('visible'); return; }
  results.innerHTML = result ? `<button data-place="${result}">${result.replace(/\b\w/g, (letter) => letter.toUpperCase())}<small>zoom to region</small></button>` : '<span>No local place match</span>';
  results.classList.add('visible');
  const button = results.querySelector('button');
  if (button) button.addEventListener('click', () => { map.flyTo({ center: placeSearch[result], zoom: 8.2, essential: true }); results.classList.remove('visible'); });
}

function setupInteractions() {
  $$('.menu-button').forEach((button) => button.addEventListener('click', toggleSidebar));
  $$('.section-tab').forEach((button) => button.addEventListener('click', () => switchSection(button.dataset.section)));
  $$('.topbar-section').forEach((button) => button.addEventListener('click', () => switchSection(button.dataset.section)));
  $$('button[data-layer]').forEach((button) => button.addEventListener('click', () => { const layer = button.dataset.layer; layers[layer] = !layers[layer]; setMapLayerVisibility(layer, layers[layer]); syncLayerControls(); }));
  $$('input[data-layer]').forEach((input) => input.addEventListener('change', () => { layers[input.dataset.layer] = input.checked; setMapLayerVisibility(input.dataset.layer, input.checked); syncLayerControls(); }));
  const timeline = $('#timeline');
  timeline.addEventListener('pointerdown', () => {
    stopPlayback();
    isTimelineScrubbing = true;
    ensureTimelineOverview();
    setReportPreviewMode(true);
    lastSliderReportUpdate = 0;
    clearTimeout(pendingSliderReportTimer);
  });
  timeline.addEventListener('input', (event) => {
    ensureTimelineOverview();
    const nextIndex = Number(event.target.value);
    cancelAnimationFrame(pendingSliderFrame);
    clearTimeout(pendingSliderReportTimer);
    pendingSliderFrame = requestAnimationFrame(() => {
      setSnapshot(nextIndex, { previewReports: true });
    });
    pendingSliderReportTimer = setTimeout(() => {
      setSnapshot(snapshotIndex, { previewReports: true });
      lastSliderReportUpdate = performance.now();
    }, 180);
  });
  timeline.addEventListener('change', (event) => {
    cancelAnimationFrame(pendingSliderFrame);
    clearTimeout(pendingSliderReportTimer);
    isTimelineScrubbing = false;
    setReportPreviewMode(false);
    setSnapshot(Number(event.target.value));
  });
  $('#timeline-back').addEventListener('click', () => { ensureTimelineOverview(); setSnapshot(snapshotIndex - 1); });
  $('#timeline-forward').addEventListener('click', () => { ensureTimelineOverview(); setSnapshot(snapshotIndex + 1); });
  $('#timeline-play').addEventListener('click', togglePlay);
}

document.addEventListener('DOMContentLoaded', () => {
  const count = observationPoints.length.toLocaleString();
  const generated = observationMetadata.generatedAt ? new Date(observationMetadata.generatedAt).toLocaleDateString() : 'unavailable';
  const evidenceCount = $('#public-observation-count');
  const evidenceSource = $('#public-observation-source');
  if (evidenceCount) evidenceCount.textContent = count;
  if (evidenceSource) evidenceSource.textContent = `GBIF public-coordinate records · refreshed ${generated}`;
  createStarfield();
  initMap();
  setupInteractions();
});
