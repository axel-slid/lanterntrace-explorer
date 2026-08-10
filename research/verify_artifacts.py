#!/usr/bin/env python3
"""Fail fast when a generated research artifact is missing or internally incomplete."""

from __future__ import annotations

import gzip
import json
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
RESULTS = ROOT / "research" / "results"
GENERATED = ROOT / "generated"


def main() -> None:
    provenance = json.loads((RESULTS / "data_provenance.json").read_text())
    if not isinstance(provenance, dict):
        raise SystemExit("data_provenance.json must contain an object")

    expected_hashes = {
        "occurrenceBundle", "hostCache", "censusStateBoundary", "worldclimElevation",
        "worldclimBioclim", "studyScript", "solverScript",
    }
    if set(provenance.get("sha256", {})) != expected_hashes:
        raise SystemExit("data provenance does not contain the complete checksum set")
    if provenance.get("analysisAccounting", {}).get("insideCensusAnalysisMask") != 57_999:
        raise SystemExit("data provenance has an unexpected included-record count")

    manifest_path = RESULTS / "included_occurrences.csv.gz"
    with gzip.open(manifest_path, "rt") as handle:
        included_rows = sum(1 for _ in handle) - 1
    if included_rows != 57_999:
        raise SystemExit(f"included occurrence manifest has {included_rows:,} rows, expected 57,999")

    required_results = {
        "temporal_metrics.csv", "bootstrap_summary.csv", "paired_comparisons.csv",
        "endpoint_comparison.csv", "parameter_sensitivity.csv", "numerical_sensitivity.csv",
        "spatial_block_metrics.csv", "annual_paired_comparisons.csv",
        "frozen_temporal_metrics.csv", "frozen_block_metrics.csv",
        "frozen_bootstrap_summary.csv", "frozen_paired_comparisons.csv",
    }
    missing = sorted(name for name in required_results if not (RESULTS / name).is_file())
    if missing:
        raise SystemExit(f"missing generated results: {', '.join(missing)}")

    benchmark_path = GENERATED / "frozen-benchmark.js"
    if not benchmark_path.is_file():
        raise SystemExit("missing generated frozen-benchmark.js app artifact")
    benchmark_text = benchmark_path.read_text()
    prefix = "window.LanternTraceBenchmark = "
    if not benchmark_text.startswith(prefix):
        raise SystemExit("frozen benchmark app artifact has an invalid wrapper")
    benchmark = json.loads(benchmark_text[len(prefix):].rstrip(";\n"))
    if benchmark.get("metadata", {}).get("targets") != [2024, 2025]:
        raise SystemExit("frozen benchmark app artifact has unexpected targets")
    if len(benchmark.get("models", [])) != 8:
        raise SystemExit("frozen benchmark app artifact must contain eight comparators")

    print("Generated provenance, manifest, and result tables verified.")


if __name__ == "__main__":
    main()
