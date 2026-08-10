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
const allowedRoots = new Set([
  '/app.js',
  '/assets',
  '/data.js',
  '/generated',
  '/index.html',
  '/main.js',
  '/node_modules',
  '/output',
  '/package.json',
  '/preload.js',
  '/styles.css',
]);
for (const entry of files) {
  const rootEntry = `/${entry.split('/').filter(Boolean)[0]}`;
  assert.ok(allowedRoots.has(rootEntry), `unexpected top-level package entry: ${entry}`);
}
for (const required of ['/index.html', '/app.js', '/data.js', '/generated/model-results.js', '/generated/frozen-benchmark.js', '/generated/observations.js']) {
  assert.ok(files.has(required), `packaged runtime file is missing: ${required}`);
}
for (const forbidden of ['/research', '/.model-cache', '/docs', '/tmp', '/catboost_info']) {
  assert.ok(![...files].some((entry) => entry === forbidden || entry.startsWith(`${forbidden}/`)), `local/research content leaked into package: ${forbidden}`);
}
const digest = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
assert.equal(digest(packagedPaper), digest(sourcePaper), 'packaged paper differs from the release PDF');
assert.ok(fs.statSync(archive).size < 90 * 1024 * 1024, 'app.asar exceeds the release size ceiling');
console.log('Verified packaged runtime allowlist, in-app paper hash, and absence of local research inputs.');
