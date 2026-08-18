#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"
export SOURCE_DATE_EPOCH=1786319357

python3 research/fetch_locked_inputs.py
python3 research/verify_inputs.py
python3 -m unittest research/test_study.py -v
python3 research/run_sota_study.py
python3 research/verify_artifacts.py
mkdir -p research/paper/build output/pdf
tectonic --keep-logs --outdir research/paper/build research/paper/lanterntrace.tex
pages="$(pdfinfo research/paper/build/lanterntrace.pdf | awk '/^Pages:/ {print $2}')"
test "$pages" = "8"

repro_check_dir="$(mktemp -d "${TMPDIR:-/tmp}/lanterntrace-pdf-check.XXXXXX")"
trap 'rm -rf -- "$repro_check_dir"' EXIT
tectonic --outdir "$repro_check_dir" research/paper/lanterntrace.tex >/dev/null
cmp research/paper/build/lanterntrace.pdf "$repro_check_dir/lanterntrace.pdf"

cp research/paper/build/lanterntrace.pdf output/pdf/lanterntrace-frontier-forecasting.pdf
shasum -a 256 output/pdf/lanterntrace-frontier-forecasting.pdf
