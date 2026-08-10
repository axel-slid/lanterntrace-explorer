#!/usr/bin/env python3
"""Verify artifacts intentionally committed for a clean checkout."""

from __future__ import annotations

import gzip
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_window_json(path: pathlib.Path, variable: str) -> dict:
    text = path.read_text()
    match = re.fullmatch(rf"window\.{re.escape(variable)}\s*=\s*(.*);\s*", text, re.DOTALL)
    if not match:
        raise AssertionError(f"Unexpected JavaScript wrapper in {path}")
    return json.loads(match.group(1))


def main() -> None:
    benchmark = load_window_json(ROOT / "generated/frozen-benchmark.js", "LanternTraceBenchmark")
    display = load_window_json(ROOT / "generated/model-results.js", "LanternTraceModels")
    assert benchmark["metadata"]["targets"] == [2024, 2025]
    assert benchmark["metadata"]["endpoint"].startswith("cells first reported")
    assert len(benchmark["models"]) == 8
    assert {model["id"] for model in benchmark["models"]} >= {
        "og_rde", "covariate_hazard", "transport_rd", "cook_2021_kernel"
    }
    assert set(benchmark["years"]) == {"2024", "2025"}
    for payload in benchmark["years"].values():
        assert payload["truthIndices"] and payload["eligibleIndices"]
        assert payload["top5CellCount"] > 0
        assert set(payload["scores"]) == {model["id"] for model in benchmark["models"]}
    assert len(display["variants"]) == 20 and len(display["topFive"]) == 5
    assert all(len(display["models"][model]["backcastFrames"]) == 84 for model in display["topFive"])

    provenance = json.loads((ROOT / "research/results/data_provenance.json").read_text())
    assert isinstance(provenance, dict) and provenance.get("sha256")
    input_lock = json.loads((ROOT / "research/input-lock.json").read_text())
    for relative in ("generated/observations.js", ".model-cache/ailanthus-altissima-ne.json"):
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == input_lock[relative]["sha256"]
    assert json.loads((ROOT / "research/results/study_summary.json").read_text())
    with gzip.open(ROOT / "research/results/included_occurrences.csv.gz", "rt") as handle:
        assert handle.readline().startswith("gbifKey,eventDate")
    pdf = ROOT / "output/pdf/lanterntrace-frontier-forecasting.pdf"
    assert pdf.read_bytes().startswith(b"%PDF-") and pdf.stat().st_size > 100_000
    print("Verified clean-clone application data, provenance, result manifest, and release PDF.")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, KeyError, OSError, json.JSONDecodeError) as error:
        print(f"Release verification failed: {error}", file=sys.stderr)
        raise SystemExit(1)
