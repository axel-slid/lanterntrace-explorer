#!/usr/bin/env node

import fs from 'node:fs/promises';

const output = new URL('../.model-cache/host-vegetation-ne.json', import.meta.url);
const bounds = { west: -82, east: -68, south: 37, north: 47 };
const recordLimit = 3600;
const pageSize = 300;

// Mean first-instar survival days are from Nixon et al. (2020),
// doi:10.1093/ee/nvaa126. They are used only as relative host weights.
const taxa = [
  { name: 'Tree-of-heaven', scientificName: 'Ailanthus altissima', taxonKey: 3190653, survivalDays: 72.5 },
  { name: 'Wild grape', scientificName: 'Vitis', taxonKey: 7467468, survivalDays: 63.9 },
  { name: 'Black walnut', scientificName: 'Juglans nigra', taxonKey: 3054357, survivalDays: 62.9 },
  { name: 'Silver maple', scientificName: 'Acer saccharinum', taxonKey: 3189837, survivalDays: 58.0 },
  { name: 'Willow', scientificName: 'Salix', taxonKey: 3039576, survivalDays: 47.0 },
  { name: 'Red maple', scientificName: 'Acer rubrum', taxonKey: 3189883, survivalDays: 22.2 },
];

const geometry = `POLYGON((${bounds.west} ${bounds.south},${bounds.east} ${bounds.south},${bounds.east} ${bounds.north},${bounds.west} ${bounds.north},${bounds.west} ${bounds.south}))`;

async function fetchPage(taxon, offset) {
  const query = new URLSearchParams({
    taxon_key: String(taxon.taxonKey),
    has_coordinate: 'true',
    has_geospatial_issue: 'false',
    occurrence_status: 'present',
    geometry,
    limit: String(pageSize),
    offset: String(offset),
  });
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const response = await fetch(`https://api.gbif.org/v1/occurrence/search?${query}`, {
      headers: { 'User-Agent': 'LanternTrace host-vegetation research snapshot' },
    });
    if (response.ok) return response.json();
    if (response.status !== 429 || attempt === 4) throw new Error(`GBIF ${taxon.name}: ${response.status}`);
    await new Promise((resolve) => setTimeout(resolve, 900 * (attempt + 1)));
  }
  throw new Error(`GBIF ${taxon.name}: retry budget exhausted`);
}

const records = [];
for (const taxon of taxa) {
  const first = await fetchPage(taxon, 0);
  const available = Number(first.count || 0);
  const pages = [first];
  const maximum = Math.min(available, recordLimit);
  for (let offset = pageSize; offset < maximum; offset += pageSize) {
    pages.push(await fetchPage(taxon, offset));
    await new Promise((resolve) => setTimeout(resolve, 180));
  }
  const seen = new Set();
  for (const page of pages) {
    for (const record of page.results || []) {
      const longitude = Number(record.decimalLongitude);
      const latitude = Number(record.decimalLatitude);
      if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) continue;
      const key = String(record.key || record.gbifID || `${longitude}:${latitude}`);
      if (seen.has(key)) continue;
      seen.add(key);
      records.push([
        taxon.taxonKey, longitude, latitude, key,
        record.license || '', record.datasetKey || '',
      ]);
    }
  }
  taxon.availableRecords = available;
  taxon.recordsUsed = seen.size;
  process.stdout.write(`${taxon.name}: ${seen.size}/${available}\n`);
}

const payload = {
  metadata: {
    name: 'Northeastern U.S. spotted-lanternfly host-vegetation occurrence snapshot',
    retrieved: new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Los_Angeles' }).format(new Date()),
    source: 'GBIF occurrence search API',
    sourceUrl: 'https://api.gbif.org/v1/occurrence/search',
    bounds,
    recordLimitPerTaxon: recordLimit,
    weighting: 'Relative mean first-instar survival days reported by Nixon et al. (2020), doi:10.1093/ee/nvaa126.',
    caveat: 'Occurrence density is an effort-biased host-availability proxy, not vegetation biomass or complete host coverage.',
    taxa,
  },
  records,
};

await fs.mkdir(new URL('../.model-cache/', import.meta.url), { recursive: true });
await fs.writeFile(output, `${JSON.stringify(payload)}\n`);
process.stdout.write(`Wrote ${records.length} host records.\n`);
