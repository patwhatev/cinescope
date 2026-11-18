"""Which pool does a graded film belong to, and should a pool be split?

A profile holds several rough taste pools (say "slow-cinema" and
"dumb-comedy"). Every pool is scored on its own, so each needs to know which
of your verdicts are *its* evidence:

  1. a verdict given in a pool's reel is tagged with that pool -- final;
  2. a film you hand-wrote into a pool's seeds.txt belongs to that pool;
  3. anything else (letterboxd imports, grades from before pools existed) is
     auto-assigned to the pool it sits closest to: theme-vector cosine to the
     pool's centroid, plus how directly letterboxd's similarity graph links
     it to the pool's films. No signal at all -> the default pool.

Assignment is recomputed on every run rather than stored, so adding a pool
or seeding one more film re-homes untagged verdicts automatically. Pin one
by hand with:  python3 pipeline/profiles.py move <slug> <pool>
"""
import collections

import common
from vectors import ThemeSpace, dot, pretty, unit

GRAPH_WEIGHT = 0.5
_memo = {}


class PoolModel:
    """Per-pool theme centroid + graph neighbourhood, built from each pool's
    seeds and its explicitly-tagged hits."""

    def __init__(self, profile, rows, films):
        self.profile = profile
        prof = common.load_profile(profile)
        self.names = list(prof.get("pools") or {})
        self.default = prof.get("default_pool") if prof.get("default_pool") in self.names \
            else (self.names[0] if self.names else None)
        cfg = common.config(profile=profile)
        sc = common.scale(cfg)
        self.films = films
        self.space = ThemeSpace(films, cfg["token_weights"])
        self.seeds = {p: dict(common.read_seeds(common.paths(profile, p).seeds))
                      for p in self.names}
        members = {p: dict(self.seeds[p]) for p in self.names}
        for slug, row in rows.items():
            p = row.get("pool")
            if p in members and slug not in members[p]:
                v = common.verdict(row, sc)
                if common.is_hit(v, sc) and v[0] in ("rating", "interest", "legacy"):
                    members[p][slug] = 0.5
        self.members = {p: {s: w for s, w in m.items() if s in films and not films[s].get("dead")}
                        for p, m in members.items()}
        self.centroid = {p: self.space.centroid((films[s], w) for s, w in m.items())
                         for p, m in self.members.items()}
        self.neigh = {}
        for p, m in self.members.items():
            nb = collections.Counter()
            for s, w in m.items():
                nb[s] += w
                for n in films[s].get("similar") or []:
                    nb[n] += w
            self.neigh[p] = (nb, max(1.0, sum(m.values()) ** 0.5))

    def affinity(self, slug):
        """{pool: score} for one film; empty when there's nothing to go on."""
        rec = self.films.get(slug)
        if not rec or rec.get("dead"):
            return {}
        tv = self.space.vec(rec)
        out = {}
        for p in self.names:
            nb, norm = self.neigh[p]
            g = nb.get(slug, 0) + sum(self.members[p].get(n, 0) for n in rec.get("similar") or [])
            score = dot(tv, self.centroid[p]) + GRAPH_WEIGHT * min(1.0, g / norm)
            if score > 0:
                out[p] = score
        return out

    def nearest(self, slug):
        aff = self.affinity(slug)
        if not aff:
            return self.default, 0.0
        ranked = sorted(aff.items(), key=lambda kv: -kv[1])
        margin = ranked[0][1] - (ranked[1][1] if len(ranked) > 1 else 0.0)
        return ranked[0][0], margin


def assign(profile=None, rows=None, films=None, detail=False):
    """{slug: pool} for every graded film in the profile (see module doc).
    With detail=True: {slug: (pool, how, margin)}, how in tagged/seed/auto/default."""
    profile = profile or common.profile_name()
    rows = common.read_db_grades(profile) if rows is None else rows
    prof = common.load_profile(profile)
    names = list(prof.get("pools") or {})
    key = (profile, tuple(sorted((s, r.get("pool"), r.get("ts")) for s, r in rows.items())),
           tuple(names), detail)
    if key in _memo:
        return _memo[key]
    out = {}
    if len(names) <= 1:
        only = names[0] if names else None
        out = {s: ((only, "only", 0.0) if detail else only) for s in rows}
        _memo[key] = out
        return out
    seeds = {p: {s for s, _ in common.read_seeds(common.paths(profile, p).seeds, hand_only=True)}
             for p in names}
    pending = []
    for slug, row in rows.items():
        p = row.get("pool")
        if p in names:
            out[slug] = (p, "tagged", 0.0) if detail else p
            continue
        homes = [q for q in names if slug in seeds[q]]
        if homes:
            out[slug] = (homes[0], "seed", 0.0) if detail else homes[0]
            continue
        pending.append(slug)
    if pending:
        model = PoolModel(profile, rows, films if films is not None else common.load_films())
        for slug in pending:
            p, margin = model.nearest(slug)
            how = "auto" if margin > 0 else "default"
            out[slug] = (p, how, margin) if detail else p
    _memo[key] = out
    return out


# ---- split suggestions ----------------------------------------------------------

def _two_means(vecs, iters=12):
    """Spherical 2-means over unit vectors; returns labels or None."""
    n = len(vecs)
    if n < 2:
        return None
    # Seed with the two least-similar members.
    best, pair = 2.0, (0, 1)
    for i in range(n):
        for j in range(i + 1, n):
            c = dot(vecs[i], vecs[j])
            if c < best:
                best, pair = c, (i, j)
    cents = [vecs[pair[0]], vecs[pair[1]]]
    labels = [0] * n
    for _ in range(iters):
        new = [0 if dot(v, cents[0]) >= dot(v, cents[1]) else 1 for v in vecs]
        cents = []
        for k in (0, 1):
            acc = collections.defaultdict(float)
            for v, lab in zip(vecs, new):
                if lab == k:
                    for t, x in v.items():
                        acc[t] += x
            cents.append(unit(acc))
        if new == labels:
            break
        labels = new
    return labels, cents


def cohesion(vecs):
    if not vecs:
        return 0.0
    c = unit({t: sum(v.get(t, 0) for v in vecs) for v in vecs for t in v})
    return sum(dot(v, c) for v in vecs) / len(vecs)


def split_suggestion(profile, pool, rows=None, films=None, min_size=4, min_share=0.2,
                     min_gain=0.05):
    """If a pool's liked films fall into two clearly different flavours,
    return {"gain", "cohesion", "groups": [{"films", "slugs", "themes"}, ...]}.

    Spherical 2-means over theme vectors of the pool's seeds and hits; a
    split is suggested when both halves are substantial (min_share of the
    pool each -- a lone outlier always "improves" cohesion) and the average
    within-group similarity rises by min_gain. Calibrated on real pools: a
    single-taste pool gains ~0.06-0.08 only by peeling off 1-2 outliers; a
    comedy + sci-fi mix gains ~0.19; horror vs. surreal art-house ~0.07."""
    films = films if films is not None else common.load_films()
    rows = common.read_db_grades(profile) if rows is None else rows
    model = PoolModel(profile, rows, films)
    asg = assign(profile, rows, films)
    sc = common.scale(common.config(pool, profile))
    members = dict(model.members.get(pool, {}))
    for slug, p in asg.items():
        if p == pool and slug in films and not films[slug].get("dead"):
            if common.is_hit(common.verdict(rows[slug], sc), sc):
                members.setdefault(slug, 0.5)
    slugs = [s for s in members if model.space.vec(films[s])]
    if len(slugs) < 2 * min_size:
        return None
    vecs = [model.space.vec(films[s]) for s in slugs]
    res = _two_means(vecs)
    if not res:
        return None
    labels, cents = res
    groups = [[i for i, lab in enumerate(labels) if lab == k] for k in (0, 1)]
    if min(len(g) for g in groups) < max(min_size, min_share * len(slugs)):
        return None
    whole = cohesion(vecs)
    split = sum(cohesion([vecs[i] for i in g]) * len(g) for g in groups) / len(vecs)
    gain = split - whole
    if gain < min_gain:
        return None
    out = []
    for k, g in enumerate(groups):
        other = cents[1 - k]
        distinct = sorted(cents[k], key=lambda t: -(cents[k][t] - other.get(t, 0)))[:5]
        g_sorted = sorted(g, key=lambda i: -dot(vecs[i], cents[k]))
        out.append({"films": [common.label(films[slugs[i]]) for i in g_sorted],
                    "slugs": [slugs[i] for i in g_sorted],
                    "themes": [pretty(t) for t in distinct]})
    return {"gain": round(gain, 3), "cohesion": round(whole, 3), "groups": out}
