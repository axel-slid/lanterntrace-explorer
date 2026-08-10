#!/usr/bin/env python3
"""Fail unless every local research input matches the committed lock."""

from __future__ import annotations

import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
lock = json.loads((ROOT / "research" / "input-lock.json").read_text())

for relative, metadata in lock.items():
    path = ROOT / relative
    if not path.exists():
        raise SystemExit(f"Missing locked input: {relative}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != metadata["sha256"]:
        raise SystemExit(f"Hash mismatch for {relative}: {digest}")
    print(f"verified {relative} {digest}")
