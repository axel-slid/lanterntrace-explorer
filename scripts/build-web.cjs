const fs = require("node:fs/promises");
const path = require("node:path");

const projectRoot = path.resolve(__dirname, "..");
const requestedTarget = process.argv[2] || path.join(projectRoot, "dist-web");
const targetRoot = path.resolve(requestedTarget);

function assertSafeTarget() {
  const parsed = path.parse(targetRoot);
  if (targetRoot === parsed.root || targetRoot === projectRoot) {
    throw new Error(`Refusing to replace unsafe web-build target: ${targetRoot}`);
  }
}

async function copy(relativeSource, relativeTarget = relativeSource) {
  const source = path.join(projectRoot, relativeSource);
  const target = path.join(targetRoot, relativeTarget);
  await fs.mkdir(path.dirname(target), { recursive: true });
  await fs.copyFile(source, target);
}

async function build() {
  assertSafeTarget();
  await fs.rm(targetRoot, { recursive: true, force: true });
  await fs.mkdir(targetRoot, { recursive: true });

  const appFiles = [
    "app.js",
    "data.js",
    "styles.css",
    "assets/lanternfly-cutout.png",
    "generated/observations.js",
    "generated/model-results.js",
    "generated/frozen-benchmark.js",
    "output/pdf/lanterntrace-frontier-forecasting.pdf",
  ];

  await Promise.all(appFiles.map((file) => copy(file)));
  await Promise.all([
    copy("node_modules/maplibre-gl/dist/maplibre-gl.css", "vendor/maplibre-gl.css"),
    copy("node_modules/maplibre-gl/dist/maplibre-gl.js", "vendor/maplibre-gl.js"),
  ]);

  const sourceHtml = await fs.readFile(path.join(projectRoot, "index.html"), "utf8");
  const webHtml = sourceHtml
    .replace(
      "./node_modules/maplibre-gl/dist/maplibre-gl.css",
      "./vendor/maplibre-gl.css",
    )
    .replace(
      "./node_modules/maplibre-gl/dist/maplibre-gl.js",
      "./vendor/maplibre-gl.js",
    )
    .replace(
      "<title>LanternTrace Explorer</title>",
      "<title>LanternTrace Explorer — Interactive Web Lab</title>",
    );

  await fs.writeFile(path.join(targetRoot, "index.html"), webHtml);

  const expected = [
    "index.html",
    ...appFiles,
    "vendor/maplibre-gl.css",
    "vendor/maplibre-gl.js",
  ];
  await Promise.all(expected.map((file) => fs.access(path.join(targetRoot, file))));

  const totalBytes = (
    await Promise.all(
      expected.map(async (file) => (await fs.stat(path.join(targetRoot, file))).size),
    )
  ).reduce((sum, size) => sum + size, 0);

  console.log(`Built browser app at ${targetRoot}`);
  console.log(`${expected.length} files · ${(totalBytes / 1024 / 1024).toFixed(1)} MB`);
}

build().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
