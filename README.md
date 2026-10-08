# Cinescope

A recommender that derives its signal from letterboxd's own film graph,
grounded in a seed set of films you already know you love, and graded against
your verdicts so it gets better each round.

## Use

```bash
./run.sh                       # crawl, score, report, build the UI, fetch posters
./serve.sh                     # start the local grading server
```

Open **http://localhost:8420**, star what you see (5★ = exactly my thing,
1★ = nothing like me — grade the *recommendation*, not the film's objective
quality), toggle "already seen" where it applies. Every star writes straight
to `data/grades.db` (sqlite) through the server's tiny JSON API — nothing to
save by hand, and it survives closing the tab.

Then fold that grading back into the model:

```bash
python3 pipeline/pull_grades.py       # data/grades.db -> out/grades.csv
python3 pipeline/tune.py              # scorecard: precision@k, channel correlation
python3 pipeline/tune.py --apply      # write the retuned weights to config.json
python3 pipeline/promote_seeds.py     # fold 4-5★ keepers into seeds.txt
python3 pipeline/update_keepers.py    # append new keepers to KEEPERS.md
ITER=03 ./run.sh                      # re-crawl with the expanded seed set, cut the next reel
```

5★ promotes a film into the seed set at full weight; 4★ at half weight —
confirmed hits shouldn't dilute the original profile's commitment to
obscure/extreme work just by also being well-connected on letterboxd (see
`KEEPERS.md` for how that got decided). Anything already graded drops to the
back of the reel so each round's top slots are fresh candidates.

## How it works

`seeds.txt` holds your profile. Four independent signal channels score every
candidate film; `config.json` holds the weights, which `tune.py` retunes from
your grading each round.

| channel | what it measures |
|---|---|
| **graph** | how many of your seeds converge on this film across letterboxd's similarity edges, decayed by distance. This is the co-occurrence signal. |
| **theme** | cosine between the film's idf-weighted theme vector and your seed centroid, using letterboxd's mini-theme taxonomy. This carries the taste *shape*. |
| **people** | director / writer / cast overlap with the people your seeds over-represent. Been the strongest predictor of your actual grades so far — see `KEEPERS.md`. |
| **quality** | letterboxd rating, shrunk toward the global mean by rating count. |

Two corrections on top:

- **Seed obscurity weighting.** A seed with 6k ratings (Sombre) is far more
  diagnostic of idiosyncratic taste than one with 3.4M (The Shining), so it
  pulls harder. Without this the canon seeds dominate and the output drifts
  toward mainstream horror.
- **Popularity adjustment.** Films so canonical they sit adjacent to
  everything get damped; deep cuts get lifted. Capped both ways so it cannot
  run away. **Watch this one** — iteration 2's scorecard showed the graph
  channel flip to a *negative* correlation with actual grades once the seed
  set tripled (well-connected hub films like Twin Peaks: The Return and Ted
  Bundy biopics clipped to the graph channel's max and crowded out real
  fits like Lost Highway and Audition). Worth a harder look before trusting
  iteration 3's ranking blindly.

## Self-hosting

`pipeline/build_ui.py` and `pipeline/serve.py` support two storage backends
for the star ratings, picked by `MODE`:

- `MODE=local` (default) — a stdlib-only Python server (`pipeline/serve.py`,
  no dependencies) serves the page and posters and backs grading with a
  sqlite file at `data/grades.db`. Runs on `localhost:8420`, this Mac only,
  started by hand with `./serve.sh`.
- `MODE=artifact` — the original version, published as a Claude Artifact and
  backed by its `db` capability. Kept working in `build_ui.py` in case it's
  ever useful again, but local is the one `run.sh` builds now.

Nothing about the scoring pipeline (crawl/score/report) differs between the
two — only where the star ratings live.

## On the data source

The thing originally wanted — raw letterboxd *list* membership overlap — is
behind Cloudflare. `/film/<slug>/lists/`, `/csi/film/<slug>/popular-lists/`,
`/films/genre/...` and `/film/<slug>/similar/` all return a 403 interstitial
to any scripted client.

What *is* open is `/film/<slug>/` and `/director|actor|writer/<slug>/`, and
between them they carry: crew, full cast (plus a clean schema.org JSON-LD
block with poster, synopsis, runtime, and billed cast), genres, themes,
mini-themes, TMDB/IMDb ids, rating and rating count, and a 6-film "Similar
Films" edge list.

Letterboxd's similarity edges are themselves distilled from list and rating
co-occurrence, so the graph channel is a *second-hand* version of the signal
originally wanted rather than the raw thing. It's a real limitation: six
edges per film is a thin graph, which is why depth-2 convergence and the
theme vector carry so much of the load — and, per the iteration-2 finding
above, why the graph channel needs watching as the seed set grows.

MovieLens 25M was evaluated as an independent co-occurrence source and
**rejected**: it has 14 ratings for Sombre, 89 for Teorema, and no Angst
(1983) at all, versus 193,026 letterboxd ratings for Gummo alone. A CF model
built on it would be driven entirely by the mainstream seeds and blind to
the transgressive core.

If the raw list data is ever worth the effort, the one viable route is
driving a real logged-in browser (the `claude-in-chrome` skill) — slow, but
it would add a genuine list-overlap channel.

## Layout

```
seeds.txt        your profile — edit freely, or let promote_seeds.py grow it
config.json      weights and thresholds — tune.py rewrites the weights
KEEPERS.md       the running list of confirmed keepers, and the taste
                 decisions made along the way
run.sh           crawl -> score -> report -> fetch posters -> build ui
serve.sh         start the local grading server (MODE=local)
pipeline/
  fetch.py           cached, throttled letterboxd fetcher (1.1s between live hits)
  parse.py           film page -> structured record (incl. the json-ld block)
  resolve.py         title + year -> slug
  crawl.py           4-phase pool construction
  score.py           the four channels
  report.py          markdown report + out/grades.csv scaffold
  build_ui.py        renders the grading page; MODE=local|artifact
  fetch_posters.py   downloads poster thumbnails for the current reel
  serve.py           the self-hosted server (stdlib only, no deps)
  pull_grades.py     data/grades.db (or an artifact dump) -> out/grades.csv
  tune.py            scorecard and reweighting
  promote_seeds.py   folds 4-5★ keepers into seeds.txt at 0.5/1.0 weight
  update_keepers.py  appends newly-kept films to KEEPERS.md
  reparse.py         re-run parse.py over cached html, no network calls
data/cache/      gzipped html, 30-day TTL
data/posters/    poster jpgs for whatever's currently in the reel
data/grades.db   your star ratings (sqlite) — the local backend's store
data/films.jsonl the pool
data/scores.json full scored output with per-channel detail
out/             reports, grades.csv, dailies.html
```
