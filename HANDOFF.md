# Cinescope — handoff context

Exported 2026-10-08 for a new agent picking this up. Repo: `/Users/patrick/Documents/DEV/cinescope` (git, 9 commits on `main`, clean working tree as of export). Self-hosted locally — **not** Claude Artifacts, by explicit choice (user's own words: "I'd prefer not to have it in claude artifacts if possible").

## The one-paragraph pitch

A personal film recommender for a very specific, extreme/arthouse taste profile (Gummo, Ken Park, Angst, Teorema, Henry: Portrait of a Serial Killer, etc. — see `seeds.txt`). It crawls letterboxd.com's own film graph (the only parts not behind Cloudflare), scores every candidate against a seed set on four signal channels, and serves the ranked result as a self-hosted local web app where the user grades films to retune the model each round. The core loop: **crawl → score → grade → re-weigh → crawl again**, run either by hand or via a one-click button in the UI itself.

## Current live state (numbers, not vibes)

- **Pool**: 1,171 films crawled, 863 scored as candidates, **39 seeds** (19 hand-stated + 20 promoted from grading)
- **Graded**: 287 rows in `data/grades.db` — 68 seen+rated, 162 unseen+want-to-see, 57 hard "never"
- **Channel weights** (`config.json`, last tuned by the user running the re-weigh button): graph 0.275, theme 0.292, people 0.290, quality 0.143
- **Seen+rated hit rate**: ~33% at last check (the real truth signal — see "the measurement bug" below for why this number matters)
- git log (oldest first): `initial setup` → self-host + sqlite + stars → serve.py schema fix + review session → two review-session keyboard corrections → watchlist + re-weigh button → director-concentration fix + scorecard bug fix → shorts/cap/interest-weight corrections → (user's own commit) more grading data

## Why self-hosted, and why that constrains the data source

Started as a Claude Artifact, moved to a local server (`pipeline/serve.py`, stdlib-only Python, zero dependencies) on explicit request. This matters for the data source story too: **letterboxd's list-overlap and similar-films pages are behind Cloudflare** and return a 403 to any scripted client — `/film/<slug>/lists/`, `/csi/.../popular-lists/`, `/films/genre/...`, `/film/<slug>/similar/` are all blocked. What **is** open: `/film/<slug>/` and `/director|actor|writer/<slug>/` — and between them they carry crew, full billed cast, genres, letterboxd's own theme/mini-theme taxonomy, a schema.org JSON-LD block (poster, synopsis, runtime, billed cast), TMDB/IMDb ids, rating + rating count, and a 6-film "Similar Films" edge list. That 6-edge list is the entire graph signal — thin, which is why the theme-vector and people channels carry so much of the load. MovieLens 25M was evaluated and **rejected** as a supplementary signal source: 14 ratings for Sombre, 89 for Teorema, zero for Angst (1983), vs 193k letterboxd ratings for Gummo — a CF model built on it would be blind to exactly the transgressive core this profile is about.

## Architecture

```
seeds.txt        profile seeds: slug | weight (0-2) | note. Hand-authored lines are
                 never touched by tooling; a marked block below them is fully
                 regenerated each run by promote_seeds.py.
config.json      every tunable knob (weights, decay rates, crawl budgets, caps)
KEEPERS.md       running list of confirmed keepers + a log of taste-boundary
                 decisions made along the way (grief-drama rejected as execution
                 not taste; found-footage rejected as weak-film not format; etc.)
run.sh           crawl -> score -> report -> fetch_posters -> build_ui (manual path)
serve.sh         starts pipeline/serve.py -> http://localhost:8420

pipeline/
  fetch.py           cached (data/cache/*.html.gz, 30-day TTL), throttled (1.1s)
                     fetcher for letterboxd film pages
  parse.py           film page -> structured record, incl. the json-ld block
  resolve.py         title+year -> slug (used once, to seed the original 19)
  crawl.py           4-phase pool builder (see below) -- the one with the
                     director-concentration fixes
  score.py           the 4 scoring channels (see below)
  report.py          markdown report + seeds out/grades.csv's column scaffold
  build_ui.py        renders out/dailies.html. MODE=local|artifact picks the
                     ~20-line storage backend; everything else is identical.
                     This file is large (~1000 lines) -- CSS, HTML, and three
                     JS feature areas (list view, review session, watchlist +
                     re-weigh) all live in one Python triple-quoted template.
  fetch_posters.py   downloads poster jpgs for whatever's in the current reel
  serve.py           the local server: static files + grades API + the
                     background pipeline-runner for the re-weigh button
  pull_grades.py     data/grades.db (or an artifact dump, legacy path) ->
                     out/grades.csv + out/watchlist.csv
  tune.py            scorecard: hit rate, precision@k, channel correlation,
                     proposed reweighting, director concentration
  promote_seeds.py   folds 4-5* seen-and-rated keepers into seeds.txt
  update_keepers.py  appends newly-kept films to KEEPERS.md
  reparse.py         re-runs parse.py over cached html, zero network calls
  common.py          shared helpers -- config(), seeds(), load_films(),
                     is_junk(), select_for_reel(), verdict(), seed_tier(),
                     next_iteration(). Read this file first; nearly every
                     scoring/weighting decision traces back to it.

data/
  cache/*.html.gz    gitignored, regenerable via fetch.py
  posters/*.jpg      gitignored, regenerable via fetch_posters.py
  grades.db          sqlite, THE durable state -- tracked in git
  films.jsonl        the crawled pool, one json record per line
  scores.json        the scored/ranked candidate list (what build_ui.py reads)
  people.json        per-run person-affinity snapshot (diagnostic, not load-bearing)
out/
  dailies.html       the built page (what serve.py serves at GET /)
  grades.csv         out/grades.db projected to CSV with a channel snapshot
                     per row (what tune.py reads)
  watchlist.csv      unseen+interest>=3 films, sorted by want-to-see
  iteration-NN.md     one per report.py run (not the same NN as KEEPERS.md's
                     own "## Iteration NN" headers -- two independent counters,
                     cosmetic inconsistency, not a bug, never reconciled)
```

## Data model — read `common.py`'s `verdict()` and `seed_tier()` first

Each graded film is one row, keyed by slug, with: `grade` (legacy pre-split 1-5 star, kept only for old rows), `status` ("seen" | "unseen" | null), `rating` (1-5, only if seen), `interest` (1-5, only if unseen), `never` (bool, only if unseen).

**`common.verdict(row)`** turns that into `(kind, value, weight)`:
- seen + rating → `("rating", rating, 1.0)` — the real truth signal, can seed
- unseen + never → `("never", 1, 1.0)` — a hard, full-weight miss
- unseen + interest → `("interest", interest, w)` where `w` comes from `INTEREST_WEIGHTS = {1: 0.15, 2: 0.3, 3: 0.55, 4: 0.8, 5: 0.95}` — **graduated by confidence, not flat**. The semantics (calibrated directly from the user's own words): 1 = no real pull yet, 2 = "yeah, maybe later", 3 = "I'll likely watch it", 4-5 = "I've been meaning to and I know it should be good". 5 sits at 0.95 — deliberately near-parity with an actual seen rating, because for this user that's what it represents.
- legacy-only (pre-split row never re-triaged) → `("legacy", grade, 1.0)`

**`common.seed_tier(row)`** — only `rating` or `legacy` verdicts can produce a seed (5★→weight 1.0 "heavy", 4★→0.5 "light"); **interest never promotes to a seed, regardless of how high.** This was a deliberate, discussed decision, not an oversight — see "A real bug we found and fixed" below for why.

## Scoring algorithm (`score.py`)

Four channels, each independently normalized to its own 95th percentile, then blended by `config.json`'s `weights`:

- **graph** — how many seeds converge on this film across letterboxd's own 6-edge similarity list, decayed by distance (depth-2 convergence). Consistently the weakest predictor of actual grades (r≈0.02-0.05) — the thin edge list just doesn't carry much signal on its own.
- **theme** — cosine similarity between the film's idf-weighted mini-theme vector and the seed centroid. Moderate predictor (r≈0.08-0.16).
- **people** — director/writer/cast overlap with people the seeds over-represent. **The strongest predictor** (r≈0.21-0.31, climbing as the interest-weight fix fed in more confident signal). This channel is also the one responsible for the director-concentration problem (see below) and is where `person_repeat_decay` lives.
- **quality** — letterboxd rating, Bayesian-shrunk toward the mean by rating count.

Corrections layered on top:
- **seed obscurity bonus** — a 6k-rating seed (Sombre) pulls harder than a 3.4M-rating one (The Shining); otherwise canon seeds dominate.
- **popularity adjustment** — damps films so canonical they sit adjacent to everything, lifts deep cuts.
- **`person_repeat_decay=0.3`** — a person's 2nd, 3rd... seed film contributes 30% of what a fresh one would (compounding: 3rd seed by the same person is 0.3² of a fresh one), both in `crawl.py`'s affinity accumulation and `score.py`'s `seed_people` channel construction. This is the fix for a real bug (next section).
- **`reel_director_cap`** — currently `null` (disabled). Was briefly set to 3 (max films per director in the fresh reel), then explicitly turned off at the user's request: "those can be shown its fine" — multiple films by a favorite director in the reel was never actually the complaint; the pool-level fixes below are what matter.

## Two real bugs found and fixed this session (both validated against live pipeline runs, not just reviewed)

**1. The director-concentration feedback loop.** Diagnosed with hard numbers, not a vibe: David Lynch had 91 entries and Takashi Miike 77 in a 917-film pool, mostly shorts/DV-art-pieces/V-cinema side-projects clearing the rating-count floor on a technicality. Root cause: `crawl.py`'s person-affinity used `+=` per seed film, so N seeds by the same director gave Nx a single-seed director's crawl priority — a rich-get-richer loop (more seeds by X → higher affinity → more of X crawled → more of X scores well → more of X kept → repeat). Fixed with: `person_repeat_decay` (above), `person_cap_per_crawl=10` (bounds how much of one person's filmography can enter the pool before the crawl budget cut), and **opportunity-director injection** — directors with exactly one strong hit (score≥55) in the prior pool who were never filmography-expanded get explored too. Validated: William Lustig went from 1 pool film to 8 (full Maniac Cop catalog), Matthew Bright 1→4, David Jacobson 1→2.

**2. A scorecard measurement bug — the tool was lying to itself.** A film promoted to a seed drops out of `scores.json` entirely (seeds aren't scored against themselves). Both `pull_grades.py` and `tune.py` independently re-derived channel data from a live `scores.json` lookup, so **every film good enough to graduate to a seed silently vanished from its own scorecard's hit-rate, mean grade, and graded-count.** Combined naive hit-rate was reporting 9%; real seen+rated hit rate is 33% (20/60). Fixed on both the write side (`pull_grades.py` now falls back to the previously-stored channel snapshot when a film is no longer a live candidate) and the read side (`tune.py` no longer requires a live `scores.json` match for the count/rate stats — only the channel-correlation section still needs one). **Known, closed limitation**: a handful of seeds promoted *before* this fix existed (Lost Highway, Audition, Dogtooth...) lost their historical channel snapshot permanently — not recoverable, documented, doesn't recur going forward.

## The UI (`out/dailies.html`, served at `http://localhost:8420`)

Three ways to grade, all writing to the same `data/grades.db`:

1. **List view** (default) — scrollable cards, poster + synopsis + why-it-was-suggested + G/T/P/Q meter. Segmented "seen it? yes/no" control, then stars (seen) or dots (unseen) + a "never" button.
2. **Review Session** — a modal, one film at a time, keyboard-driven for fast triage:
   - Stage 1 "seen it?" — `←` no / `→` yes (plain, just sets status, no verdict yet)
   - Stage 2 "rate" — `1`-`5` keys (enjoyment if seen, want-to-see if unseen), or `←`/`X` = "not at all, excluded from weighting" **only in the unseen branch** (this took two iterations to get right — see git log messages on the two "review session" fix commits for the wrong designs that preceded it)
   - Auto-advances through everything not yet reviewed; `Esc` exits anytime, nothing lost (each answer saves immediately)
3. **Watchlist viewer** — click the "watchlist" stat in the tally bar; read-only list of unseen+interest≥3, sorted by want-to-see, pure client-side (no new endpoint).

**Re-weigh & Generate New Pool button** — runs the entire feedback loop as a background job on the server and reloads onto the result: `pull_grades → tune --apply → promote_seeds → update_keepers → crawl → score → report → fetch_posters → build_ui`. Confirms first (hits letterboxd repeatedly, crawl can take several minutes). Progress streams into a log panel via polling (`GET /api/reweigh`); closing the panel only stops this tab's polling, the job keeps running server-side; a page reload resumes watching it automatically if still going. This is the main lever for "make it better" — triggered via `POST /api/reweigh` on `pipeline/serve.py`, which spawns each pipeline step as a subprocess with live-streamed stdout into a bounded in-memory log (`pipeline_state` in serve.py, thread-safe via a lock).

## Known gaps / open threads for whoever picks this up

1. **README.md is stale** — still describes the pre-seen/unseen-split flow (flat 1-5 "+/- Keep" stars) and doesn't mention Review Session, Watchlist, or the Re-weigh button at all. Don't trust it; this document is current as of export.
2. **Unseen-interest targeting is the weakest area** — only ~13/112 want-to-see guesses landed 4-5★ at last full check, before the graduated-weight fix. Not yet re-validated with a fresh grading round under the new weights.
3. **Anthology/omnibus films** (many co-directors, e.g. "Paris, Je T'aime", "42 One Dream Rush") can still ride past the (now-disabled anyway) director cap and aren't addressed by the shorts filter either, since they're usually feature-length. Not flagged as a problem by the user, just noted as unaddressed.
4. `person_films()` in `crawl.py` takes filmography entries in whatever order letterboxd's page lists them when applying `person_cap_per_crawl` — not quality-sorted (that data isn't available until a film's own page is fetched). A rough heuristic, not perfectly principled.
5. Two independent "iteration" counters exist (`update_keepers.py`'s own `## Iteration NN` headers in KEEPERS.md vs `common.next_iteration()`'s `out/iteration-NN.md` numbering) — cosmetic, never reconciled, low priority.
6. The most recent commit (`improved weighting, better user flow, seeding more data`) was made by the user directly (not this session) — just more grading data (`data/grades.db` binary diff), no code changes. Worth running `git log -p` on it only if you need to confirm that.

## How to pick this up

```bash
cd /Users/patrick/Documents/DEV/cinescope
./serve.sh                    # if not already running -- http://localhost:8420
# grade via the browser (list view, review session, or watchlist)
# then either click "Re-weigh & Generate New Pool" in the UI, or by hand:
python3 pipeline/pull_grades.py
python3 pipeline/tune.py            # read the scorecard before --apply
python3 pipeline/tune.py --apply
python3 pipeline/promote_seeds.py
python3 pipeline/update_keepers.py
python3 pipeline/crawl.py           # slow -- hits letterboxd repeatedly
python3 pipeline/score.py
python3 pipeline/fetch_posters.py
MODE=local python3 pipeline/build_ui.py
```

Commit after grading sessions and after re-weighs — `data/grades.db`, `data/films.jsonl`, `data/scores.json`, `config.json`, `seeds.txt`, `KEEPERS.md`, and `out/*` are all tracked; `data/cache/` and `data/posters/` are gitignored (large, regenerable).
