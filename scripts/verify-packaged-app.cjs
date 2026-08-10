const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const asar = require('@electron/asar');

const root = path.resolve(__dirname, '..');
const resources = path.join(root, 'dist', 'mac-arm64', 'LanternTrace Explorer.app', 'Contents', 'Resources');
const archive = path.join(resources, 'app.asar');
const packagedPaper = path.join(resources, 'app.asar.unpacked', 'output', 'pdf', 'lanterntrace-frontier-forecasting.pdf');
const sourcePaper = path.join(root, 'output', 'pdf', 'lanterntrace-frontier-forecasting.pdf');

assert.ok(fs.existsSync(archive), 'packaged app.asar is missing');
assert.ok(fs.existsSync(packagedPaper), 'unpacked in-app paper is missing');
const files = new Set(asar.listPackage(archive));
for (const required of ['/index.html', '/app.js', '/data.js', '/generated/model-results.js', '/generated/frozen-benchmark.js']) {
  assert.ok(files.has(required), `packaged runtime file is missing: ${required}`);
}
for (const forbidden of ['/generated/observations.js', '/research', '/.model-cache', '/docs']) {
  assert.ok(![...files].some((entry) => entry === forbidden || entry.startsWith(`${forbidden}/`)), `local/research content leaked into package: ${forbidden}`);
}
const digest = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
assert.equal(digest(packagedPaper), digest(sourcePaper), 'packaged paper differs from the release PDF');
assert.ok(fs.statSync(archive).size < 150 * 1024 * 1024, 'app.asar exceeds the release size ceiling');
console.log('Verified packaged runtime allowlist, in-app paper hash, and absence of local research inputs.');
