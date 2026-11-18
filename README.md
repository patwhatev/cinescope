# Cinescope

A local film recommender built on letterboxd's own film graph. You give it a
few films that define a taste. It crawls what letterboxd links to them,
scores every candidate, and serves a grading page. Your verdicts then retune
it each round.

It has no opinion of its own about what's good. Rom-coms, anime, slasher
films and slow cinema all go through the same machinery, and everything
specific to a person lives in that person's **profile**.

Self-hosted, standard-library Python 3.9+, no accounts, no dependencies, no
services beyond letterboxd itself.

## Profiles and pools

```
profiles/<person>/            one per person on this machine (gitignored)
  profile.json                person-wide settings: rating scale, popularity lean, boosts...
  grades.db                   every verdict, tagged with the pool it was given in
  watchlist.csv, KEEPERS.md
  pools/<pool>/               one rough taste: "dumb-comedy", "slow-sci-fi", "90s-anime"...
    seeds.txt                 the films that define it
    scores.json, dailies.html, grades.csv, reports/
data/                         shared letterboxd metadata cache (gitignored)
defaults.json                 neutral starting settings
```

Most people's taste is several tastes. If you blend a comedy pool and an
arthouse pool into one profile vector, you get recommendations that suit
neither. So **each pool is scored on its own**: it has its own seeds, its own
theme centroid, its own graph walk, its own learned channel weights, and its
own reel. A **mix** reel interleaves all of them.

Some things are about the person, not the mood, and apply across every pool:

- **Never.** "Don't show me things like this." It pushes away films similar
  to it, the people in it, and its flavour of theme, in every pool. The theme
  penalty is softer outside the pool where you said it
  (`cross_pool_theme_penalty`).
- **Rating scale.** What each number means to you (see below).
- **Person-wide settings.** Popularity lean, people boosts, junk filters.

### Where a verdict counts

A grade given in a pool's reel belongs to that pool. Imports and older grades
carry no pool, so they're **auto-assigned** to the nearest pool. "Nearest"
combines theme similarity to the pool's centroid with how directly
letterboxd's graph links the film to the pool's films. Assignment is
recomputed every run, so a new pool picks up the verdicts that fit it. Pin a
film by hand with `profiles.py move`. `profiles.py suggest` flags a pool
whose liked films fall into two distinct groups, and shows both groups.

## Quick start

```bash
python3 pipeline/profiles.py new alex                 # creates profiles/alex, pool "main"
python3 pipeline/profiles.py seed main "Paddington 2|2017" "Hot Fuzz|2007" "The Nice Guys|2016"
python3 pipeline/profiles.py pool add anime "hand-drawn, quiet, melancholy"
python3 pipeline/profiles.py seed anime "Perfect Blue|1997" "Mind Game|2004"

./run.sh alex          # crawl + score + build every pool (minutes; cached after)
./serve.sh             # -> http://localhost:8420
```

Or start from a letterboxd account. Watched films, star ratings and the
watchlist all become verdicts, and auto-assignment sorts them into pools:

```bash
python3 pipeline/import_letterboxd.py <letterboxd-user> --profile alex --dry-run
python3 pipeline/import_letterboxd.py <letterboxd-user> --profile alex
```

A pool still needs at least one seed, either hand-written or promoted from a
5★ verdict on a re-weigh.

Other commands:

```bash
python3 pipeline/profiles.py list | use <name> | show
python3 pipeline/profiles.py assign [--pool P] [--all]   # where each verdict landed, and why
python3 pipeline/profiles.py move <slug> <pool>          # pin one
python3 pipeline/profiles.py suggest                     # pools that look like two tastes
./run.sh alex anime                                      # just one pool
./serve.sh --lan                                         # grade from your phone on the same wifi
```

## Grading

On the page: **seen it?** If yes, give stars for how much you enjoyed it. If
no, give dots for how much you want to watch it, or **never**. There's also a
keyboard review session for working through a backlog, a watchlist (with
"watched it → rate"), and **Re-weigh**, which runs the whole loop in the
background and reloads:

pull grades → tune weights → promote seeds → crawl → score → report → build

### Rating scales

People use five stars differently, so the scale is a per-profile preset
(`"scale"` in profile.json; see `common.SCALES`):

| | `standard` (default) | `top-heavy` |
|---|---|---|
| meaning | 3 fine · 4 liked · 5 loved | 3 already a solid yes · 4–5 rare |
| hit | 4+ | 3+ |
| becomes a seed | 5 (heavy) · 4 (light) | 5 (heavy) · 4 (light) |
| pushes away | ≤2 | ≤2 |
| letterboxd import | straight across | shifted down a step |

Want-to-see never becomes a seed, however high. That takes a real watch.

## How scoring works

Four channels. Each is normalised by its own 95th percentile, then blended
by weights that `tune.py` learns per pool from your grades:

| channel | measures |
|---|---|
| **graph** | how many of the pool's seeds converge on the film through letterboxd's "similar films" edges, decayed by distance |
| **theme** | cosine between the film's idf-weighted theme vector (letterboxd mini-themes, themes, genres) and the pool's centroid |
| **people** | director / writer / cast overlap with people the seeds over-represent. It only counts in full when graph or theme back it up (`people_gate_floor`) |
| **quality** | letterboxd rating, Bayesian-shrunk toward the mean by rating count |

Corrections, all in settings:

- **`person_repeat_decay`.** A person's 2nd, 3rd... seed film confirms the
  affinity rather than multiplying it, so a few prolific favourites can't
  swamp the crawl budget. `person_cap_per_crawl` bounds it further, and
  "opportunity directors" spend some budget on directors with a single
  strong hit.
- **Anchors.** A pool's hits that aren't seeds act as lighter extra sources,
  so the search widens beyond the seeds alone.
- **Negative anchors.** Nevers and dislikes, from every pool. Their theme
  penalty uses only what sets them apart from the pool. The part they share
  with it is projected out, so the pool doesn't penalise itself.
- **`reel_director_decay`.** Spreads the reel across directors.
- **`junk`.** Featurettes are dropped. Shorts must be well-known *and*
  well-regarded. `max_directors` can drop anthologies.
- **`popularity_lean`.** 0 is neutral; above 0 lifts lesser-known films,
  below 0 favours well-known ones.
- **`seed_obscurity_bonus`.** 0 is neutral; above 0 makes lesser-known
  seeds pull harder.

Settings resolve in this order: `defaults.json`, then the profile's
`settings`, then the pool's `settings`. `tune.py --apply` writes learned
weights into the pool once it has `tune.min_rows` graded films. Until then
the pool inherits the profile's weights.

## On the data source

Only `/film/<slug>/` and `/director|actor|writer/<slug>/` serve to scripted
clients. Letterboxd's list, genre and similar-film pages sit behind
Cloudflare. Between them, the open pages carry crew, billed cast, genres,
themes, mini-themes, poster/synopsis/runtime (JSON-LD), TMDB/IMDb ids,
rating and count, and a short "similar films" edge list. That edge list is
the whole graph signal, which is why the theme and people channels carry so
much. Fetches are cached in `data/cache/` (30 days) and throttled to about 1
per second.

## Layout

```
defaults.json        neutral settings
run.sh / serve.sh    pipeline for a profile / local server
pipeline/
  common.py          paths, settings, rating scales, verdict semantics -- start here
  pools.py           verdict -> pool assignment, split suggestions
  vectors.py         theme vectors
  profiles.py        CLI: profiles, pools, seeds, assignment
  fetch.py parse.py resolve.py   letterboxd fetch / parse / title -> slug
  crawl.py           4-phase pool construction (seeds -> depth 1 -> depth 2 -> people)
  score.py           the four channels
  pull_grades.py     grades.db -> pool grades.csv + profile watchlist.csv
  tune.py            scorecard + learned weights
  promote_seeds.py   seed-tier verdicts -> the pool's seeds.txt
  update_keepers.py  KEEPERS.md
  report.py          markdown report per iteration
  build_ui.py        the grading page (pool or mix). MODE=local|artifact
  fetch_posters.py   poster cache
  serve.py           local server + background re-weigh
  import_letterboxd.py  watched / ratings / watchlist -> grades.db
  okru_walk.py       step through a watchlist, one search tab per film
  reparse.py         re-run parse.py over cached html, no network
```
