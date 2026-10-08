# Cinescope

A recommender that derives its signal from letterboxd's own film graph,
grounded in a seed set of films you already know you love, and graded against
your verdicts so it gets better each round.

## How it works

`seeds.txt` holds your profile. Four independent signal channels score every
candidate film; `config.json` holds the weights, which the grading loop tunes.

| channel | what it measures |
|---|---|
| **graph** (0.40) | how many of your seeds converge on this film across letterboxd's similarity edges, decayed by distance. This is the co-occurrence signal. |
| **theme** (0.30) | cosine between the film's idf-weighted theme vector and your seed centroid, using letterboxd's mini-theme taxonomy. This carries the taste *shape*. |
| **people** (0.18) | director / writer / cast overlap with the people your seeds over-represent. |
| **quality** (0.12) | letterboxd rating, shrunk toward the global mean by rating count. |

Two corrections on top:

- **Seed obscurity weighting.** A seed with 6k ratings (Sombre) is far more
  diagnostic of idiosyncratic taste than one with 3.4M (The Shining), so it
  pulls harder. Without this the canon seeds dominate and the output drifts
  toward mainstream horror.
- **Popularity adjustment.** Films so canonical they sit adjacent to
  everything get damped; deep cuts get lifted. Capped both ways so it cannot
  run away.

## On the data source

The thing you asked for — raw letterboxd *list* membership overlap — is behind
Cloudflare. `/film/<slug>/lists/`, `/csi/film/<slug>/popular-lists/`,
`/films/genre/...` and `/film/<slug>/similar/` all return a 403 interstitial to
any scripted client.

What *is* open is `/film/<slug>/` and `/director|actor|writer/<slug>/`, and
between them they carry: crew, full cast, genres, themes, mini-themes,
TMDB/IMDb ids, rating and rating count, and a 6-film "Similar Films" edge list.

Letterboxd's similarity edges are themselves distilled from list and rating
co-occurrence, so the graph channel is a *second-hand* version of the signal
you wanted rather than the raw thing. It is a real limitation, not a free
substitution: six edges per film is a thin graph, which is why depth-2
convergence and the theme vector carry so much of the load.

MovieLens 25M was evaluated as an independent co-occurrence source and
**rejected**: it has 14 ratings for Sombre, 89 for Teorema, and no Angst (1983)
at all, versus 193,026 letterboxd ratings for Gummo alone. A CF model built on
it would be driven entirely by the four mainstream seeds and blind to the
transgressive core.

If you want the raw list data, the one viable route is driving a real logged-in
browser (the `claude-in-chrome` skill) — slow, but it would add a genuine
list-overlap channel.

## Use

```bash
./run.sh                  # crawl, score, report  (ITER=02 TOP=60 ./run.sh)
```

Then open `out/iteration-01.md`, and fill in the `grade` column of
`out/grades.csv`:

- `grade` 1-5 — 5 = exactly my thing, 1 = nothing like me. **Grade the
  recommendation, not the film's quality.**
- `seen` — `y` if you had already watched it. High "already seen" means good
  targeting but poor novelty.
- `note` — free text.

```bash
python3 pipeline/tune.py            # scorecard + proposed weights
python3 pipeline/tune.py --apply    # write the new weights, then re-run
```

Anything you grade is excluded from later iterations, so each round surfaces
fresh films. Anything you grade `5` is printed as a line ready to paste into
`seeds.txt`.

## Layout

```
seeds.txt        your profile — edit freely
config.json      weights and thresholds — tune.py rewrites the weights
run.sh           crawl -> score -> report
pipeline/
  fetch.py       cached, throttled letterboxd fetcher (1.1s between live hits)
  parse.py       film page -> structured record
  resolve.py     title + year -> slug
  crawl.py       4-phase pool construction
  score.py       the four channels
  report.py      markdown report + grading sheet
  tune.py        scorecard and reweighting
data/cache/      gzipped html, 30-day TTL
data/films.jsonl the pool
data/scores.json full scored output with per-channel detail
out/             reports and grades.csv
```
