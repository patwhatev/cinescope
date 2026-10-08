#!/bin/bash
# Full pipeline. Safe to re-run: every letterboxd page is cached on disk,
# so a second run costs almost no requests.
set -e
cd "$(dirname "$0")"
ITER="${ITER:-01}"
echo "== crawl ==";         python3 pipeline/crawl.py
echo "== score ==";         python3 pipeline/score.py
echo "== report ==";        ITER="$ITER" TOP="${TOP:-40}" python3 pipeline/report.py
echo "== fetch posters =="; BUILD_TOP="${BUILD_TOP:-80}" python3 pipeline/fetch_posters.py
echo "== build ui ==";      ITER="$ITER" MODE="${MODE:-local}" BUILD_TOP="${BUILD_TOP:-80}" python3 pipeline/build_ui.py
echo
echo "Done. Start grading with: ./serve.sh   (then open http://localhost:8420)"
