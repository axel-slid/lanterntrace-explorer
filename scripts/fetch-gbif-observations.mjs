import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const GBIF_ENDPOINT = 'https://api.gbif.org/v1/occurrence/search';
const TAXON_KEY = '5157899';
const PAGE_SIZE = 300;
const CONCURRENCY = 4;
const outputPath = resolve('generated/observations.js');
const execFileAsync = promisify(execFile);

const baseParams = new URLSearchParams({
  taxon_key: TAXON_KEY,
  country: 'US',
  has_coordinate: 'true',
  has_geospatial_issue: 'false',
  occurrence_status: 'present'
});

async function fetchJson(url) {
  const { stdout } = await execFileAsync('curl', [
    '-sS', '--fail', '--retry', '5', '--retry-all-errors', '--max-time', '60',
    '-H', 'User-Agent: LanternTrace Explorer research prototype', url
  ], { maxBuffer: 50 * 1024 * 1024 });
  return JSON.parse(stdout);
}

async function fetchPage(offset, eventDate) {
  const params = new URLSearchParams(baseParams);
  params.set('limit', String(PAGE_SIZE));
  params.set('offset', String(offset));
  if (eventDate) params.set('event_date', eventDate);
  return fetchJson(`${GBIF_ENDPOINT}?${params}`);
}

function compactRecord(record) {
  const date = record.eventDate || '';
  return [
    Number(record.decimalLongitude),
    Number(record.decimalLatitude),
    date.slice(0, 10),
    String(record.key),
    record.stateProvince || '',
    record.locality || record.county || '',
    record.basisOfRecord || '',
    record.datasetKey || '',
    record.license || '',
    record.occurrenceID || ''
  ];
}

const countParams = new URLSearchParams(baseParams);
countParams.set('limit', '0');
const sourceCount = (await fetchJson(`${GBIF_ENDPOINT}?${countParams}`)).count;
const monthRanges = [{ label: 'pre-2017', eventDate: '1000-01-01,2016-12-31' }];
for (let year = 2017; year <= new Date().getUTCFullYear(); year += 1) {
  for (let month = 0; month < 12; month += 1) {
    const start = `${year}-${String(month + 1).padStart(2, '0')}-01`;
    const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
    const end = `${year}-${String(month + 1).padStart(2, '0')}-${lastDay}`;
    monthRanges.push({ label: start.slice(0, 7), eventDate: `${start},${end}` });
  }
}

const pages = [];
let cursor = 0;
let fetchedRecords = 0;
async function worker() {
  while (cursor < monthRanges.length) {
    const range = monthRanges[cursor++];
    const firstPage = await fetchPage(0, range.eventDate);
    pages.push(firstPage);
    fetchedRecords += firstPage.results.length;
    for (let offset = PAGE_SIZE; offset < firstPage.count; offset += PAGE_SIZE) {
      const page = await fetchPage(offset, range.eventDate);
      pages.push(page);
      fetchedRecords += page.results.length;
    }
    if (firstPage.count) process.stdout.write(`Fetched ${range.label}: ${firstPage.count.toLocaleString()} records (${fetchedRecords.toLocaleString()} total)\n`);
  }
}
await Promise.all(Array.from({ length: CONCURRENCY }, worker));

const byKey = new Map();
for (const page of pages) {
  for (const record of page.results) {
    if (!Number.isFinite(record.decimalLongitude) || !Number.isFinite(record.decimalLatitude)) continue;
    byKey.set(String(record.key), compactRecord(record));
  }
}

const observations = [...byKey.values()].sort((a, b) => (a[2] || '').localeCompare(b[2] || '') || Number(a[3]) - Number(b[3]));
const datedCount = observations.filter((record) => /^\d{4}-\d{2}-\d{2}$/.test(record[2])).length;
const generatedAt = new Date().toISOString();
const payload = {
  metadata: {
    source: 'GBIF occurrence API',
    sourceUrl: `https://www.gbif.org/species/${TAXON_KEY}`,
    scientificName: 'Lycorma delicatula (White, 1845)',
    taxonKey: TAXON_KEY,
    country: 'United States',
    filters: 'hasCoordinate=true; hasGeospatialIssue=false; occurrenceStatus=PRESENT',
    generatedAt,
    sourceCount,
    count: observations.length,
    datedCount,
    excludedUndatedCount: Math.max(0, sourceCount - observations.length)
  },
  observations
};

await mkdir(dirname(outputPath), { recursive: true });
await writeFile(outputPath, `window.LanternTraceObservations = ${JSON.stringify(payload)};\n`);
process.stdout.write(`Wrote ${observations.length.toLocaleString()} public-coordinate records to ${outputPath}\n`);
