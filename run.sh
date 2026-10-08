#!/bin/bash
# Full pipeline. Safe to re-run: every letterboxd page is cached on disk,
# so a second run costs almost no requests.
set -e
cd "$(dirname "$0")"
ITER="${ITER:-01}"
echo "== crawl ==";  python3 pipeline/crawl.py
echo "== score ==";  python3 pipeline/score.py
echo "== report =="; ITER="$ITER" TOP="${TOP:-40}" python3 pipeline/report.py
