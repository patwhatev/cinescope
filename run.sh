#!/bin/bash
# Full pipeline for one profile -- every pool, or just one.
#
#   ./run.sh                    active profile, every pool
#   ./run.sh alex               profile "alex", every pool
#   ./run.sh alex comedy        just the "comedy" pool
#
# Safe to re-run: every letterboxd page is cached on disk, so a second run
# costs almost no requests. Grading feedback (pull/tune/promote) runs first
# so a re-run picks up whatever you've graded since.
set -e
cd "$(dirname "$0")"
[ -n "$1" ] && export CINESCOPE_PROFILE="$1"
PROFILE="$(python3 -c 'import sys; sys.path.insert(0,"pipeline"); import common; print(common.profile_name())')"
export CINESCOPE_PROFILE="$PROFILE"
if [ -n "$2" ]; then
  POOLS="$2"
else
  POOLS="$(python3 -c 'import sys; sys.path.insert(0,"pipeline"); import common; print(" ".join(common.pools()))')"
fi

for POOL in $POOLS; do
  export CINESCOPE_POOL="$POOL"
  ITER="$(python3 -c 'import sys; sys.path.insert(0,"pipeline"); import common; print(common.next_iteration())')"
  echo "######## $PROFILE / $POOL  (iteration $ITER) ########"
  echo "== pull grades ==";   python3 pipeline/pull_grades.py
  echo "== tune ==";          python3 pipeline/tune.py --apply || true
  echo "== promote seeds =="; python3 pipeline/promote_seeds.py
  echo "== crawl ==";         python3 pipeline/crawl.py
  echo "== score ==";         python3 pipeline/score.py
  echo "== report ==";        ITER="$ITER" TOP="${TOP:-40}" python3 pipeline/report.py
  echo "== fetch posters =="; python3 pipeline/fetch_posters.py
  echo "== build ui ==";      ITER="$ITER" MODE="${MODE:-local}" python3 pipeline/build_ui.py
done
echo "== update keepers =="; python3 pipeline/update_keepers.py
if [ "$(python3 -c 'import sys; sys.path.insert(0,"pipeline"); import common; print(len(common.pools()))')" -gt 1 ]; then
  echo "== build mix =="; CINESCOPE_POOL=mix MODE="${MODE:-local}" python3 pipeline/build_ui.py || true
fi
echo
echo "Done. Start grading with: ./serve.sh   (then open http://localhost:8420)"
