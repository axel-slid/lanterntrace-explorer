const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const context = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(root, 'generated/frozen-benchmark.js'), 'utf8'), context);

const benchmark = context.window.LanternTraceBenchmark;
const pastId = 'cook_2021_kernel';
const oursId = 'eco_rd';

function topIndices(yearData, modelId) {
  return new Set(yearData.eligibleIndices
    .map((index) => [index, yearData.scores[modelId][index]])
    .sort((left, right) => right[1] - left[1])
    .slice(0, yearData.top5CellCount)
    .map(([index]) => index));
}

function verifyYear(year, expected) {
  const yearData = benchmark.years[String(year)];
  assert.ok(yearData, `Missing frozen data for ${year}`);
  for (const modelId of [pastId, 'fisher_kpp', 'climate_rd', oursId]) {
    assert.equal(yearData.scores[modelId].length, benchmark.metadata.grid.rows * benchmark.metadata.grid.columns, `${modelId} score grid is incomplete for ${year}`);
  }
  const truth = new Set(yearData.truthIndices);
  const pastTop = topIndices(yearData, pastId);
  const oursTop = topIndices(yearData, oursId);
  const hits = (indices) => [...indices].filter((index) => truth.has(index)).length;
  const movedIn = [...oursTop].filter((index) => !pastTop.has(index)).length;
  assert.equal(hits(pastTop), expected.pastHits, `Unexpected Cook-2021 top-5% hits for ${year}`);
  assert.equal(hits(oursTop), expected.oursHits, `Unexpected Eco-RD top-5% hits for ${year}`);
  assert.equal(movedIn, expected.movedIn, `Unexpected reallocated-cell count for ${year}`);
}

verifyYear(2024, { pastHits: 31, oursHits: 36, movedIn: 18 });
verifyYear(2025, { pastHits: 26, oursHits: 35, movedIn: 18 });
console.log('Verified Cook-2021 → Eco-RD explanation counts for 2024 and 2025.');
