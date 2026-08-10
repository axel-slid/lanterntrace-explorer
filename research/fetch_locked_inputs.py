#!/usr/bin/env python3
"""Fetch redistributable upstream archives and verify every locked input."""

from __future__ import annotations

import hashlib
import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "research/input-lock.json").read_text())
URLS = {
    ".model-cache/cb_2025_us_state_500k.zip": "https://www2.census.gov/geo/tiger/GENZ2025/kml/cb_2025_us_state_500k.zip",
    ".model-cache/wc2.1_10m_elev.zip": "https://geodata.ucdavis.edu/climate/worldclim/2_1/base/wc2.1_10m_elev.zip",
    ".model-cache/wc2.1_10m_bio.zip": "https://geodata.ucdavis.edu/climate/worldclim/2_1/base/wc2.1_10m_bio.zip",
}


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


for relative, metadata in LOCK.items():
    target = ROOT / relative
    if target.exists():
        if sha256(target) != metadata["sha256"]:
            raise SystemExit(f"Existing locked input has wrong hash; refusing to overwrite: {relative}")
        print(f"ready {relative}")
        continue
    url = URLS.get(relative)
    if not url:
        raise SystemExit(f"Missing committed locked input: {relative}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".download")
    print(f"fetching {relative}")
    request = urllib.request.Request(url, headers={"User-Agent": "LanternTrace research artifact"})
    with urllib.request.urlopen(request, timeout=240) as response, temporary.open("wb") as handle:
        while chunk := response.read(1024 * 1024):
            handle.write(chunk)
    if sha256(temporary) != metadata["sha256"]:
        temporary.unlink(missing_ok=True)
        raise SystemExit(f"Downloaded input failed checksum: {relative}")
    temporary.replace(target)
    print(f"verified {relative}")
