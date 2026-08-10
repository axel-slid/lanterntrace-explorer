# LanternTrace Explorer

Interactive application and public research benchmark for spotted-lanternfly frontier forecasting.

**[Read the technical paper](output/pdf/lanterntrace-frontier-forecasting.pdf)**

![LanternTrace Explorer frozen first-report evaluation](docs/screenshot.png)

## Quick start

```bash
npm ci
npm start
```

The clean checkout includes the frozen 2024–2025 benchmark, exploratory monthly display models, and checksum-locked occurrence-point snapshot used in the report. Tested development environment: macOS arm64, Node 25, npm 11, and Python 3.13. Node 22+ is recommended.

For a full local model rebuild:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r research/requirements-lock.txt
npm run model:build
npm start
```

`npm run data:gbif` is available only when intentionally refreshing to the current GBIF index; it does not recreate the locked 2 August 2026 snapshot. Exact reproduction uses the committed occurrence and host snapshots, downloads the three immutable Census/WorldClim archives with platform-CA-aware `curl`, and verifies all five hashes in `research/input-lock.json`. Tectonic and Poppler (`pdfinfo`, `pdftotext`, `pdftoppm`) are required to rebuild and inspect the paper. Public CI repeats archive retrieval, all scientific tests, the frozen analysis rebuild, and artifact-drift checks from a clean checkout.

## What is included

- A default frozen-evaluation view for 2024 and 2025 first reports, fixed top-5% allocations, AP, R@5%, geographic-block intervals, and Cook et al. (2021) as a historical literature comparator.
- Report-derived evidence envelopes and explicitly labeled reporting-gap interpolation.
- Twenty exploratory reaction–diffusion display variants with 84 monthly evidence-assimilating steps and Settings-only 2026–2030 scenarios.
- A map comparison of model allocations and observed first reports, built-in place search, and JSON export of the active scientific view.
- Public-coordinate GBIF occurrence support, schematic corridor hypotheses, and illustrative proposed sites clearly separated from operational recommendations.

The frozen benchmark asks which previously unreported 0.2° U.S. land cells are first reported in a target year. Relative risk ranks are not occupancy probabilities. The 2024–2025 coefficient freeze improves temporal separation, but it was designed from a 2026 snapshot and is not preregistered field validation.

The exploratory monthly playback is a different product: dated reports re-anchor each historical step. Its legacy composite scores are not forecast validation or calibrated confidence. Prospective scenarios are off at launch, and their lower-threshold envelope is a sensitivity display rather than an uncertainty interval.

Basemap © OpenStreetMap contributors via OpenFreeMap. Occurrences © GBIF contributors.

## Verification and packaging

Verify the committed app and paper artifacts in a clean checkout:

```bash
npm run verify:release
```

With the locked scientific inputs available, regenerate the study, run ten research tests, rebuild all eight figures, compile the 11-page paper twice, and require byte-identical PDFs:

```bash
research/reproduce.sh
```

The PDF is written to `output/pdf/lanterntrace-frontier-forecasting.pdf`. The full benchmark includes the transferred Cook et al. (2021) spotted-lanternfly dispersal kernel, covariate and distance baselines, and reaction–diffusion models. Generated tables, frozen app benchmark, exploratory display models, locked occurrence/host snapshots, and release PDF are committed. The build fetches stable Census and WorldClim archives and verifies every checksum; see `research/input-lock.json`, `research/fetch_locked_inputs.py`, `DATA_LICENSE.md`, and `research/results/data_provenance.json`.

```bash
npm run pack
```

Packaging first runs the clean-clone and packaged-runtime verifiers. The macOS arm64 release is development-signed but not Apple-notarized, so Gatekeeper may require an explicit user override.

## Scope, citation, and reuse

LanternTrace is a research prototype for hypothesis-driven search prioritization—not quarantine, treatment, inspection, or agency guidance. It does not infer abundance, verified occupancy, or calibrated detection probability.

Use `CITATION.cff` for the software citation and cite Cook et al. (2021) when discussing the transferred historical comparator. Third-party data retain their source licenses as documented in `DATA_LICENSE.md`. The current software notice reserves reuse rights; archive DOI, funding, and competing-interest statements remain to be confirmed before journal submission.
