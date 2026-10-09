# Cinescope

A recommender that derives its signal from letterboxd's own film graph,
grounded in a seed set of films you already know you love, and graded against
your verdicts so it gets better each round. Self-hosted, local, no accounts,
no external services beyond letterboxd itself.

See `HANDOFF.md` for a fuller export of where things stand and why — this
file is the quick-start and reference.

## Use

```bash
./serve.sh                     # start the local grading server -> http://localhost:8420
```

Open the page and grade however suits the moment:

- **List view** (default) — scroll, answer "seen it?" per card, then star how
  much you enjoyed it (seen) or how inclined you are to watch it (unseen).
- **Run Review Session** — a single-card, keyboard-driven triage flow for
  going through a backlog fast: `←`/`→` for seen-it, then `1`-`5` to rate
  (unseen: `←` or `X` = not at all, fully excluded from weighting). `Esc`
  exits anytime; every answer saves immediately, nothing is lost.
- **Watchlist** — click the "watchlist" number in the tally bar: everything
  unseen you rated 3+ on want-to-see, sorted by how much you want to see it.

Grading writes straight to `data/grades.db` (sqlite) through the server's own
tiny JSON API — nothing to save by hand.

When you've graded a batch, click **Re-weigh & Generate New Pool** in the UI.
It runs the whole feedback loop as a background job and reloads onto the
result when done (confirms first — it hits letterboxd repeatedly and the
re-crawl step can take several minutes; closing the progress panel doesn't
stop it, a reload resumes watching). Equivalent by hand:

```bash
python3 pipeline/pull_grades.py       # data/grades.db -> out/grades.csv (+ out/watchlist.csv)
python3 pipeline/tune.py              # scorecard: hit rate, precision@k, channel correlation
python3 pipeline/tune.py --apply      # write the retuned weights to config.json
python3 pipeline/promote_seeds.py     # fold seen+rated 4-5★ keepers into seeds.txt
python3 pipeline/update_keepers.py    # append new keepers to KEEPERS.md
python3 pipeline/crawl.py             # re-crawl with the expanded seed set (slow)
python3 pipeline/score.py
python3 pipeline/fetch_posters.py
MODE=local python3 pipeline/build_ui.py
```

**Only a seen-and-rated 5★ or 4★ promotes a film into the seed set** (1.0 /
0.5 weight) — an unseen want-to-see rating, however high, never does. That
split exists on purpose: early on, several films got promoted as heavy seeds
from a flat pre-split rating that actually meant "I want to see this," not "I
watched and loved this," and it skewed the model until caught. See `KEEPERS.md`
for the taste-boundary calls made along the way, and `HANDOFF.md` for the
longer version of that story.

## How it works

`seeds.txt` holds your profile — hand-authored lines plus a marked block
`promote_seeds.py` regenerates from grading each round. Four independent
signal channels score every candidate film; `config.json` holds the weights
and every tunable knob, which `tune.py --apply` rewrites from your grading.

| channel | what it measures |
|---|---|
| **graph** | how many of your seeds converge on this film across letterboxd's similarity edges, decayed by distance. The weakest predictor by far (r≈0.02-0.05) — six edges per film just doesn't carry much. |
| **theme** | cosine between the film's idf-weighted theme vector and your seed centroid, using letterboxd's mini-theme taxonomy. Carries the taste *shape*. |
| **people** | director / writer / cast overlap with the people your seeds over-represent. The strongest predictor (r≈0.21-0.31) — and the one that needed the most correction, below. |
| **quality** | letterboxd rating, Bayesian-shrunk toward the mean by rating count. |

Corrections layered on top, roughly in order of how much they matter:

- **Person-affinity decays per repeat.** A person's 2nd, 3rd... seed film
  confirms the affinity rather than multiplying it (`person_repeat_decay =
  0.3`). Without this, N seeds by the same director gave them Nx a
  single-seed director's crawl priority — which is exactly how the pool
  ended up with 91 David Lynch entries and 77 Takashi Miike entries (mostly
  shorts and side-projects) in a 917-film pool, and 38% of the reel from
  directors already seeded. `person_cap_per_crawl = 10` bounds it further at
  crawl time, and **opportunity-director injection** spends some of the
  freed budget exploring directors with exactly one strong hit who've never
  had their filmography pulled (this is how William Lustig's Maniac Cop
  catalog, Matthew Bright's Freeway films, and David Jacobson's other work
  entered the pool).
- **Shorts need to be revered, not just counted.** Anything under 40 minutes
  needs ≥5,000 ratings *and* ≥3.7 average to survive `is_junk()`'s filter —
  the general rating-count floor alone let obscure DV-art-piece shorts
  through on a technicality. A short that's genuinely beloved (e.g. "David
  Lynch Cooks Quinoa," ~20k ratings, 4.3★) still gets in.
- **Want-to-see weight is graduated, not flat.** `common.INTEREST_WEIGHTS =
  {1: 0.15, 2: 0.3, 3: 0.55, 4: 0.8, 5: 0.95}` — "yeah, maybe later" (2) and
  "I've been meaning to and I know it should be good" (4-5) are very
  different confidence levels, and training weight now reflects that; 5 sits
  near parity with an actual seen rating.
- **Seed obscurity weighting.** A seed with 6k ratings (Sombre) is far more
  diagnostic of idiosyncratic taste than one with 3.4M (The Shining), so it
  pulls harder.
- **Popularity adjustment.** Films so canonical they sit adjacent to
  everything get damped; deep cuts get lifted.
- **Reel director cap: disabled on purpose.** There's a `reel_director_cap`
  knob in `config.json` (currently `null`) that can limit how many films by
  one director show up in a single reel. Tried it, then turned it back off —
  showing several films by a favorite director was never actually the
  problem; the crawl-side fixes above are what matters.

A real measurement bug, now fixed: a film promoted to a seed drops out of
`scores.json` (seeds aren't scored against themselves), and the scorecard
used to require a live match there for its hit-rate/mean-grade stats — so
every film good enough to graduate to a seed was silently excluded from its
own scorecard. Combined hit-rate was reporting 9%; the real seen+rated hit
rate is 33%. `pull_grades.py` and `tune.py` no longer need a live candidate
match for those stats.

## Self-hosting

`pipeline/build_ui.py` supports two storage backends for the grading data,
picked by `MODE`:

- `MODE=local` (default) — `pipeline/serve.py`, a stdlib-only Python server
  with zero dependencies, serves the page and posters, backs grading with
  sqlite at `data/grades.db`, and runs the re-weigh pipeline as a background
  job. `localhost:8420`, this machine only, started by hand with `./serve.sh`.
- `MODE=artifact` — the original version, published as a Claude Artifact and
  backed by its `db` capability. Left working in `build_ui.py` in case it's
  useful again, but local is the one actually in use.

Nothing about the scoring pipeline differs between the two — only where the
grading data lives, and whether the re-weigh button has a server to run on
(it's hidden automatically in `MODE=artifact`, since there's no subprocess
pipeline to trigger on claude.ai).

## On the data source

The thing originally wanted — raw letterboxd *list* membership overlap — is
behind Cloudflare. `/film/<slug>/lists/`, `/csi/film/<slug>/popular-lists/`,
`/films/genre/...` and `/film/<slug>/similar/` all return a 403 interstitial
to any scripted client.

What *is* open is `/film/<slug>/` and `/director|actor|writer/<slug>/`, and
between them they carry: crew, full billed cast, genres, themes, mini-themes,
a schema.org JSON-LD block (poster, synopsis, runtime, billed cast), TMDB/IMDb
ids, rating and rating count, and a 6-film "Similar Films" edge list — the
entire graph signal this tool has to work with.

Letterboxd's similarity edges are themselves distilled from list and rating
co-occurrence, so the graph channel is a *second-hand* version of the signal
originally wanted. Six edges per film is thin, which is why the theme vector
and the people channel (and its corrections, above) carry so much of the load.

MovieLens 25M was evaluated as an independent co-occurrence source and
**rejected**: 14 ratings for Sombre, 89 for Teorema, zero for Angst (1983),
versus 193,026 letterboxd ratings for Gummo alone. A CF model built on it
would be driven entirely by the mainstream seeds and blind to the
transgressive core this profile is actually about.

If the raw list data is ever worth the effort, the one viable route is
driving a real logged-in browser (the `claude-in-chrome` skill) — slow, but
it would add a genuine list-overlap channel.

## Layout

```
seeds.txt        your profile — hand-authored lines + a block promote_seeds.py regenerates
config.json      every tunable knob — tune.py --apply rewrites the weights
KEEPERS.md       the running list of confirmed keepers, and the taste-boundary
                 decisions made along the way
HANDOFF.md       fuller context export — architecture, data model, known gaps
run.sh           crawl -> score -> report -> fetch posters -> build ui (manual path)
serve.sh         start the local server (MODE=local) -> http://localhost:8420
pipeline/
  fetch.py           cached, throttled letterboxd fetcher (1.1s between live hits)
  parse.py           film page -> structured record, incl. the json-ld block
  resolve.py         title + year -> slug
  crawl.py           4-phase pool construction (seeds -> depth1 -> depth2 -> people)
  score.py           the four channels
  report.py          markdown report + out/grades.csv column scaffold
  build_ui.py        renders the grading page: list view, review session,
                     watchlist, re-weigh button. MODE=local|artifact.
  fetch_posters.py   downloads poster thumbnails for the current reel
  serve.py           the self-hosted server + the background pipeline runner
  pull_grades.py     data/grades.db (or an artifact dump) -> out/grades.csv
  tune.py            scorecard, channel correlation, proposed reweighting,
                     director concentration
  promote_seeds.py   folds seen+rated 4-5★ keepers into seeds.txt at 0.5/1.0
  update_keepers.py  appends newly-kept films to KEEPERS.md
  reparse.py         re-run parse.py over cached html, no network calls
  common.py          shared helpers — read this first. verdict() and
                     seed_tier() define what every grade actually means.
data/cache/      gzipped html, 30-day TTL (gitignored, regenerable)
data/posters/    poster jpgs for whatever's in the current reel (gitignored)
data/grades.db   your grading, durable state — tracked in git
data/films.jsonl the crawled pool
data/scores.json full scored/ranked output with per-channel detail
out/             reports, grades.csv, watchlist.csv, dailies.html
```
