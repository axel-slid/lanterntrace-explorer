const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const context = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(root, 'generated/frozen-benchmark.js'), 'utf8'), context);

const benchmark = context.window.LanternTraceBenchmark;
const modelIds = ['fisher_kpp', 'climate_rd', 'transport_rd', 'full_mechanistic', 'og_rde'];
const { rows, columns } = benchmark.metadata.grid;

for (const year of [2024, 2025]) {
  const yearData = benchmark.years[String(year)];
  const eligible = new Set(yearData.eligibleIndices);
  for (const modelId of modelIds) {
    const scores = yearData.scores[modelId];
    assert.equal(scores.length, rows * columns, `${modelId} physics surface is incomplete for ${year}`);
    assert.ok(yearData.eligibleIndices.every((index) => Number.isFinite(scores[index]) && scores[index] >= 0 && scores[index] <= 1), `${modelId} has an invalid relative-rank value for ${year}`);
    let nonzeroGradients = 0;
    for (const index of yearData.eligibleIndices) {
      const row = Math.floor(index / columns);
      const column = index % columns;
      if (row % 3 !== 1 || column % 3 !== 1) continue;
      const center = scores[index];
      const value = (neighbor) => eligible.has(neighbor) ? scores[neighbor] : center;
      const dx = (value(index + 1) - value(index - 1)) / 2;
      const dy = (value(index + columns) - value(index - columns)) / 2;
      if (Math.hypot(dx, dy) >= .012) nonzeroGradients += 1;
    }
    assert.ok(nonzeroGradients >= 20, `${modelId} does not produce a useful vector field for ${year}`);
  }
}

const appSource = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const htmlSource = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
for (const marker of ['lt-physics-field', 'lt-physics-height', 'lt-physics-front', 'lt-physics-vectors']) assert.ok(appSource.includes(marker), `Missing physics map layer ${marker}`);
assert.ok(htmlSource.includes('id="physics-view-inline"'), 'Missing Physics View toggle');
assert.ok(appSource.includes('not abundance, calibrated velocity, or a literal time forecast'), 'Missing physics-view interpretation caveat');

console.log('Verified five frozen physics surfaces, local gradient vectors, map layers, and interpretation labeling.');
