"""Shared paths, settings, and grading semantics.

Layout:

  defaults.json                       neutral settings every profile starts from
  data/                               shared, taste-agnostic film metadata
    films.jsonl, cache/, posters/
  profiles/<profile>/                 one person (gitignored)
    profile.json                      person-wide settings + the pool list
    grades.db                         every verdict, tagged with the pool it came from
    watchlist.csv, KEEPERS.md
    dailies.html                      the "mix" reel across all pools
    pools/<pool>/                     one rough taste pool ("slow-cinema", "dumb-comedy"...)
      seeds.txt, scores.json, people.json, grades.csv, dailies.html, reports/

Which profile/pool a script works on comes from CINESCOPE_PROFILE and
CINESCOPE_POOL (run.sh / serve.py set them). Without them: the profile named
in profiles/.active, else the only profile there is; the profile's
default_pool, else its first pool.

Settings resolve defaults.json <- profile.json "settings" <- the pool's
"settings", so a pool can override anything (usually just the channel
weights, once it has enough grades for tune.py to learn them).
"""
import collections
import copy
import json
import os
import re
import sqlite3

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DATA = os.path.join(ROOT, "data")
PROFILES = os.path.join(ROOT, "profiles")
DEFAULTS_PATH = os.path.join(ROOT, "defaults.json")
MIX = "mix"

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


# ---- profiles & pools -------------------------------------------------------

def list_profiles():
    if not os.path.isdir(PROFILES):
        return []
    return sorted(n for n in os.listdir(PROFILES)
                  if os.path.isfile(os.path.join(PROFILES, n, "profile.json")))


def profile_name():
    name = os.environ.get("CINESCOPE_PROFILE")
    if name:
        return name
    active = os.path.join(PROFILES, ".active")
    if os.path.exists(active):
        name = open(active, encoding="utf-8").read().strip()
        if name:
            return name
    found = list_profiles()
    if len(found) == 1:
        return found[0]
    if not found:
        raise SystemExit("no profiles yet -- create one:  python3 pipeline/profiles.py new <name>")
    raise SystemExit("several profiles (%s) -- pick one with CINESCOPE_PROFILE=<name> "
                     "or python3 pipeline/profiles.py use <name>" % ", ".join(found))


def profile_dir(profile=None):
    return os.path.join(PROFILES, profile or profile_name())


def load_profile(profile=None):
    path = os.path.join(profile_dir(profile), "profile.json")
    if not os.path.exists(path):
        raise SystemExit("no profile %r (expected %s)" % (profile or profile_name(), path))
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_profile(data, profile=None):
    path = os.path.join(profile_dir(profile), "profile.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def pools(profile=None):
    return list(load_profile(profile).get("pools") or {})


def pool_name(profile=None):
    name = os.environ.get("CINESCOPE_POOL")
    if name:
        return name
    prof = load_profile(profile)
    names = list(prof.get("pools") or {})
    if not names:
        raise SystemExit("profile %r has no pools -- python3 pipeline/profiles.py pool add <pool>"
                         % (profile or profile_name()))
    return prof.get("default_pool") if prof.get("default_pool") in names else names[0]


def pool_dir(pool=None, profile=None):
    return os.path.join(profile_dir(profile), "pools", pool or pool_name(profile))


class Paths:
    """Every per-profile / per-pool file a pipeline step touches."""

    def __init__(self, profile=None, pool=None):
        self.profile = profile or profile_name()
        self.pool = pool or pool_name(self.profile)
        self.profile_dir = profile_dir(self.profile)
        self.pool_dir = os.path.join(self.profile_dir, "pools", self.pool)
        self.grades_db = os.path.join(self.profile_dir, "grades.db")
        self.watchlist = os.path.join(self.profile_dir, "watchlist.csv")
        self.keepers = os.path.join(self.profile_dir, "KEEPERS.md")
        self.mix_html = os.path.join(self.profile_dir, "dailies.html")
        self.seeds = os.path.join(self.pool_dir, "seeds.txt")
        self.scores = os.path.join(self.pool_dir, "scores.json")
        self.people = os.path.join(self.pool_dir, "people.json")
        self.grades_csv = os.path.join(self.pool_dir, "grades.csv")
        self.dailies = os.path.join(self.pool_dir, "dailies.html")
        self.reports = os.path.join(self.pool_dir, "reports")

    def for_pool(self, pool):
        return Paths(self.profile, pool)


def paths(profile=None, pool=None):
    return Paths(profile, pool)


# ---- settings -----------------------------------------------------------------

def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def defaults():
    with open(DEFAULTS_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def config(pool=None, profile=None):
    """defaults.json <- profile settings <- pool settings."""
    cfg = defaults()
    try:
        prof = load_profile(profile)
    except SystemExit:
        return cfg
    cfg = _merge(cfg, prof.get("settings"))
    pool = pool or os.environ.get("CINESCOPE_POOL") or None
    if pool and pool != MIX:
        cfg = _merge(cfg, ((prof.get("pools") or {}).get(pool) or {}).get("settings"))
    return cfg


def set_pool_setting(key, value, pool=None, profile=None):
    prof = load_profile(profile)
    pool = pool or pool_name(profile)
    entry = prof.setdefault("pools", {}).setdefault(pool, {})
    entry.setdefault("settings", {})[key] = value
    save_profile(prof, profile)


# ---- seeds & films ------------------------------------------------------------

SEED_MARKER = "# --- promoted from grading (regenerated by pipeline/promote_seeds.py) ---"


def read_seeds(path, hand_only=False):
    """[(slug, weight)] from a seeds.txt. hand_only stops at the marker
    above which seeds are hand-written (below it, promote_seeds.py owns)."""
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if hand_only and line.strip() == SEED_MARKER:
                break
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            out.append((parts[0], float(parts[1]) if len(parts) > 1 and parts[1] else 1.0))
    return out


def seeds(pool=None, profile=None):
    return read_seeds(paths(profile, pool).seeds)


def load_films():
    path = os.path.join(DATA, "films.jsonl")
    films = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    films[rec["slug"]] = rec
    return films


def save_films(films):
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, "films.jsonl")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for slug in sorted(films):
            fh.write(json.dumps(films[slug], ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---- junk filter --------------------------------------------------------------

JUNK = re.compile(
    r"making of|behind the scenes|director'?s journey|a look at|featurette|"
    r"interview|outtakes|deleted scenes|anniversary|commentary|trailer|"
    r"\bdocumentary about\b", re.I)


def is_junk(rec, cfg=None):
    """Featurettes, making-ofs and near-unrated entries pollute filmographies.

    Shorts get a stricter bar than the general floor: a director's stray
    music video clears min_rating_count on a technicality without being what
    "more like this director's work" means, so a short only survives if it's
    well-known AND well-regarded. Both bars, and an optional cap on director
    count (anthologies ride in on whichever famous co-director a profile
    likes), live under "junk" in the settings.
    """
    cfg = cfg or config()
    j = cfg.get("junk", {})
    if JUNK.search(rec.get("title") or ""):
        return True
    max_dirs = j.get("max_directors")
    if max_dirs and len(rec.get("directors") or []) > max_dirs:
        return True
    if (rec.get("rating_count") or 0) < cfg.get("min_rating_count", 0):
        return True
    runtime = rec.get("runtime")
    if runtime and runtime < j.get("short_max_runtime", 40):
        if (rec.get("rating_count") or 0) < j.get("short_min_rating_count", 5000):
            return True
        if (rec.get("rating") or 0) < j.get("short_min_rating", 3.7):
            return True
    return False


def label(rec):
    return "%s (%s)" % (rec.get("title") or rec["slug"], rec.get("year") or "?")


def select_for_reel(films_sorted, top, cfg=None):
    """Fresh (ungraded) candidates lead; already-graded films trail so a
    revisit is still possible but never crowds out new material. Shared by
    build_ui.py and fetch_posters.py so their film lists can't drift apart.

    The fresh front is re-ranked for spread: each film a director already
    has in the reel multiplies their next one's score by
    `reel_director_decay`, so a favorite still shows up (their best film
    competes at full strength) but the reel reads as a spread of neighbours
    rather than one filmography. `reel_director_cap`, if set, is a hard
    ceiling on top of that.
    """
    cfg = cfg or config()
    cap = cfg.get("reel_director_cap")
    decay = cfg.get("reel_director_decay", 1.0)
    pending = [f for f in films_sorted if not f["already_graded"]]
    reviewed = [f for f in films_sorted if f["already_graded"]]
    fresh, overflow, seen_dir = [], [], collections.Counter()

    def eff(f):
        dirs = f.get("directors") or []
        n = max((seen_dir[d] for d in dirs), default=0)
        return f["score"] * decay ** n

    # Greedy: films_sorted is already score-ordered and decay only ever
    # lowers a score, so each pick only needs to scan until the raw score
    # can no longer beat the best effective score found so far.
    while pending and len(fresh) < top:
        best_i, best = 0, -1.0
        for i, f in enumerate(pending):
            if f["score"] <= best:
                break
            e = eff(f)
            if e > best:
                best_i, best = i, e
        f = pending.pop(best_i)
        dirs = f.get("directors") or []
        if cap and dirs and max(seen_dir[d] for d in dirs) >= cap:
            overflow.append(f)
            continue
        for d in dirs:
            seen_dir[d] += 1
        fresh.append(f)
    return (fresh + overflow + pending + reviewed)[:top]


# ---- rating scales -----------------------------------------------------------
# A grade answers one of two questions depending on whether you've seen the
# film: "how much did you enjoy it" (rating 1-5) or "how much do you want to
# see it" (interest 1-5, or `never`). People use a 5-point scale differently,
# so what each number *means* -- which count as hits, which become seeds,
# how much a want-to-see should train the weights -- is a per-profile preset.
#
#   hit_min          ratings / interest at or above this are hits
#   miss_max         at or below this is a firm miss
#   dislike_max      seen ratings at or below this push away (between this and
#                    hit_min is neutral)
#   seed_tiers       seen rating -> seed weight (5 heavy, 4 light, typically)
#   interest_weights how hard each want-to-see level trains the weights
#   watchlist_interest  interest given to a letterboxd watchlist import
#   letterboxd       [min half-stars, rating] pairs, highest first

SCALES = {
    "standard": {
        "description": "5 stars used the ordinary way: 3 is fine, 4 liked, 5 loved.",
        "hit_min": 4, "miss_max": 1, "dislike_max": 2,
        "seed_tiers": {"5": 1.0, "4": 0.5},
        "interest_weights": {"1": 0.45, "2": 0.25, "3": 0.25, "4": 0.7, "5": 0.9},
        "watchlist_interest": 4,
        "letterboxd": [[9, 5], [7, 4], [5, 3], [3, 2], [0, 1]],
        "rating_tips": {"5": "loved it -- weighs heavy as a seed",
                        "4": "liked it -- weighs light as a seed",
                        "3": "fine -- neutral", "2": "didn't like it", "1": "hated it"},
        "interest_tips": {"5": "must see", "4": "want to watch",
                          "3": "maybe", "2": "probably not", "1": "no"},
    },
    "top-heavy": {
        "description": "4-5 are rare; 3 is already a solid yes.",
        "hit_min": 3, "miss_max": 1, "dislike_max": 2,
        "seed_tiers": {"5": 1.0, "4": 0.5},
        "interest_weights": {"1": 0.45, "2": 0.25, "3": 0.7, "4": 0.9, "5": 0.95},
        "watchlist_interest": 3,
        "letterboxd": [[9, 5], [8, 4], [6, 3], [4, 2], [0, 1]],
        "rating_tips": {"5": "loved it -- weighs heavy as a seed",
                        "4": "really liked it -- weighs light as a seed",
                        "3": "good -- a hit, widens the search",
                        "2": "didn't like it", "1": "hated it"},
        "interest_tips": {"5": "must see -- rare", "4": "really want to -- rare",
                          "3": "solid want to watch", "2": "maybe later",
                          "1": "no, I don't really think so"},
    },
}


def scale(cfg=None):
    """The active scale preset, with any per-profile overrides merged in.
    Settings key "scale" is a preset name, or {"preset": name, ...overrides}."""
    cfg = cfg or config()
    s = cfg.get("scale") or "standard"
    if isinstance(s, str):
        s = {"preset": s}
    base = SCALES.get(s.get("preset", "standard"), SCALES["standard"])
    return _merge(base, {k: v for k, v in s.items() if k != "preset"})


GRADE_COLS = ["rank", "slug", "title", "year", "score", "g", "t", "p", "q",
              "grade", "seen", "rating", "interest", "never", "pool", "note"]

# `never` is not "a 1": it's "this is offensive / plain bad, don't show me
# things like this". It sits below the scale, outweighs a seen rating, and
# score.py also uses it as a negative anchor in every pool.
NEVER_VALUE = 0.0
NEVER_WEIGHT = 1.25
INTEREST_WEIGHT = 0.5   # fallback for a stray non-1-5 interest value


def _num(v):
    try:
        return float(str(v).strip()) if v not in (None, "") else None
    except ValueError:
        return None


def _s(v):
    return "" if v is None else str(v).strip().lower()


def _flag(v):
    return _s(v) in ("y", "yes", "1", "true")


def _seen(v):
    return _s(v) in ("y", "yes", "1", "true", "seen")


def _unseen(v):
    return _s(v) in ("n", "no", "0", "false", "unseen")


def verdict(row, sc=None):
    """One grade row -> (kind, value, weight), or None if ungraded. Accepts a
    grades.csv row (seen=y/n) or a grades.db row (status=seen/unseen).

      seen + rating      -> ("rating",   rating,   1.0)     enjoyment; can seed
      unseen + never     -> ("never",    0,        1.25)    "don't show me things like this"
      unseen + interest  -> ("interest", interest, w)       w from the scale; never seeds
      only an old grade  -> ("legacy",   grade,    1.0)     pre-split, ambiguous
    """
    sc = sc or scale()
    # grades.db rows carry `status`; grades.csv rows carry `seen` (y/n). An
    # old db can still have a stale pre-split `seen` column -- status wins.
    seen = row.get("status") if "status" in row else row.get("seen")
    rating, interest = _num(row.get("rating")), _num(row.get("interest"))
    if _seen(seen) and rating:
        return ("rating", rating, 1.0)
    if _unseen(seen) and _flag(row.get("never")):
        return ("never", NEVER_VALUE, NEVER_WEIGHT)
    if _unseen(seen) and interest:
        w = sc["interest_weights"].get(str(int(interest)), INTEREST_WEIGHT)
        return ("interest", interest, w)
    grade = _num(row.get("grade"))
    if grade:
        return ("legacy", grade, 1.0)
    return None


def seed_tier(row, sc=None):
    """Seed weight for a film you've seen and loved, else None. Only seen
    ratings (or an untriaged old grade) promote -- interest never does."""
    sc = sc or scale()
    v = verdict(row, sc)
    if not v or v[0] not in ("rating", "legacy"):
        return None
    return sc["seed_tiers"].get(str(int(v[1])))


def is_hit(v, sc=None):
    return v is not None and v[1] >= (sc or scale())["hit_min"]


def is_miss(v, sc=None):
    return v is not None and v[1] <= (sc or scale())["miss_max"]


# ---- grades -----------------------------------------------------------------
# grades.db is the source of truth, one row per film per profile. `pool` is
# the pool whose reel the verdict was given in (null for imports); pools.py
# assigns untagged rows to their nearest pool.

GRADE_DB_COLUMNS = ["slug", "title", "grade", "status", "rating", "interest",
                    "never", "pool", "ts"]


def grades_db(profile=None):
    path = os.path.join(profile_dir(profile), "grades.db")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE IF NOT EXISTS grades(
        slug TEXT PRIMARY KEY, title TEXT, grade INTEGER, status TEXT,
        rating INTEGER, interest INTEGER, never INTEGER, pool TEXT, ts INTEGER
    )""")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(grades)")}
    for col, typ in (("status", "TEXT"), ("rating", "INTEGER"), ("interest", "INTEGER"),
                     ("never", "INTEGER"), ("pool", "TEXT")):
        if col not in cols:
            conn.execute("ALTER TABLE grades ADD COLUMN %s %s" % (col, typ))
    conn.commit()
    return conn


def read_db_grades(profile=None):
    """{slug: row dict} straight from grades.db."""
    path = os.path.join(profile_dir(profile), "grades.db")
    if not os.path.exists(path):
        return {}
    conn = grades_db(profile)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(grades)")]
    rows = conn.execute("SELECT %s FROM grades" % ", ".join(cols)).fetchall()
    conn.close()
    return {r[0]: dict(zip(cols, r)) for r in rows}


def read_grades(path=None):
    """The current pool's grades.csv (verdicts + channel snapshots)."""
    path = path or paths().grades_csv
    if not os.path.exists(path):
        return {}
    import csv
    with open(path, encoding="utf-8") as fh:
        return {r["slug"]: r for r in csv.DictReader(fh)}


def _holdout():
    hold = set()
    if os.environ.get("CINESCOPE_HOLDOUT"):
        with open(os.environ["CINESCOPE_HOLDOUT"], encoding="utf-8") as fh:
            hold = {ln.strip() for ln in fh if ln.strip()}
    return hold


def anchors(pool=None, profile=None, assignment=None):
    """Graded films that steer scoring and crawling beyond the seeds:
    (positive {slug: weight}, negative {slug: weight}, neg_home {slug: pool}).

    Positive -- only from this pool: hits that aren't already seeds (a seen
    film at hit_min+ below the seed tiers, a want-to-see at hit_min+), so
    recommendations fan out across what you like *in this pool* instead of
    just around its seed set. Negative -- from every pool, because "don't
    show me things like this" is about you, not one mood: nevers at full
    weight, disliked seen films at less, a firm "no" want-to-see at a touch.
    neg_home lets score.py soften the theme penalty for nevers given in a
    different pool (see cross_pool_theme_penalty).
    """
    import pools as _pools
    cfg = config(pool, profile)
    sc = scale(cfg)
    pool = pool or pool_name(profile)
    a = cfg.get("anchors", {})
    pos_w = a.get("positive", {"rating": 0.45, "interest": 0.35})
    neg_w = a.get("negative", {"never": 1.0, "rating": 0.5, "interest": 0.15})
    rows = read_db_grades(profile)
    if assignment is None:
        assignment = _pools.assign(profile, rows)
    hold = _holdout()
    pos, neg, home = {}, {}, {}
    for slug, row in rows.items():
        if slug in hold:
            continue
        v = verdict(row, sc)
        if not v:
            continue
        kind, val, _ = v
        here = assignment.get(slug) == pool
        if kind == "never":
            neg[slug] = neg_w["never"]
        elif kind in ("rating", "legacy"):
            if val <= sc["dislike_max"]:
                neg[slug] = neg_w["rating"] * (1.0 if val <= sc["miss_max"] else 0.6)
            elif here and val >= sc["hit_min"] and not sc["seed_tiers"].get(str(int(val))):
                pos[slug] = pos_w["rating"]
        elif kind == "interest":
            if val <= sc["miss_max"]:
                neg[slug] = neg_w["interest"]
            elif here and val >= sc["hit_min"]:
                pos[slug] = pos_w["interest"] * (1 + 0.25 * (val - sc["hit_min"]))
        if slug in neg:
            home[slug] = assignment.get(slug)
    return pos, neg, home


def triage_slugs(reel_slugs, pool=None, profile=None, assignment=None):
    """Graded films belonging to this pool that the reel doesn't carry
    (promoted seeds, films that fell out of the top slice), so they can still
    be re-triaged."""
    import pools as _pools
    pool = pool or pool_name(profile)
    rows = read_db_grades(profile)
    if assignment is None:
        assignment = _pools.assign(profile, rows)
    mine = {s for s, p in assignment.items() if p == pool}
    return sorted(mine - set(reel_slugs))


def next_iteration(reports_dir=None):
    """Smallest unused "NN" for reports/iteration-NN.md, zero-padded."""
    reports_dir = reports_dir or paths().reports
    best = 0
    if os.path.isdir(reports_dir):
        for name in os.listdir(reports_dir):
            m = re.match(r"iteration-(\d+)\.md$", name)
            if m:
                best = max(best, int(m.group(1)))
    return "%02d" % (best + 1)
