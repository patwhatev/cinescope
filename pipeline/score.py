"""Score every crawled film against one pool's seeds.

Four independent channels, each normalised by its own 95th percentile so the
weights mean what they say and stay comparable when tuning:

  graph    how many of the pool's seeds converge on this film, decayed by
           distance. Letterboxd's similarity edges are themselves distilled
           from list/rating overlap, so breadth of convergence is the signal.
  theme    cosine between the film's idf-weighted theme vector and the
           centroid of the pool's seeds. Mini-themes carry the shape; genre
           is coarse.
  people   director/writer/cast overlap with the people the seeds
           over-represent. Gated by graph/theme: a shared director only
           counts in full when the film is also *like* the pool -- otherwise
           every stray side-project of a favorite outranks its neighbours.
  quality  letterboxd rating, shrunk toward the global mean by rating count.

Grading feeds in beyond the seed set (common.anchors): this pool's hits are
extra, lighter graph/theme sources, so the reel fans out across what you
like here. Nevers and dislikes from *every* pool push away -- letterboxd-
similar to a never, the flavour of theme that sets nevers apart from this
pool, and the people in them.

`popularity_lean` then tilts by rating count: positive lifts lesser-known
films, negative favours well-known ones, 0 leaves them alone.
"""
import collections
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import pools
from vectors import ThemeSpace, dot, unit

P = common.paths()
CFG = common.config(P.pool)


def pct(values, p):
    if not values:
        return 1.0
    xs = sorted(values)
    i = min(len(xs) - 1, max(0, int(round(p / 100.0 * (len(xs) - 1)))))
    return xs[i] or 1.0


def popnorm(count):
    if not count:
        return 0.0
    return min(1.0, max(0.0, (math.log10(count) - 3.5) / 3.0))


def main():
    films = common.load_films()
    seedlist = common.read_seeds(P.seeds)
    if not seedlist:
        sys.exit("pool %r has no seeds yet -- add some to %s" % (P.pool, P.seeds))
    wmap = dict(seedlist)
    seed_slugs = [s for s, _ in seedlist if s in films and not films[s].get("dead")]
    seedset = set(seed_slugs)

    rows_db = common.read_db_grades(P.profile)
    assignment = pools.assign(P.profile, rows_db, films)
    done = {s for s, r in rows_db.items()
            if common.verdict(r) or common._seen(r.get("status"))}
    pos_anchor, neg_anchor, neg_home = common.anchors(P.pool, P.profile, assignment)
    pos_anchor = {s: w for s, w in pos_anchor.items() if s in films and s not in seedset
                  and not films[s].get("dead")}
    neg_anchor = {s: w for s, w in neg_anchor.items() if s in films and not films[s].get("dead")}
    NEG = CFG["never_penalty"]
    cross = CFG.get("cross_pool_theme_penalty", 1.0)

    # Optional: lesser-known seeds pull harder than the canon entries
    # everybody has seen (0 by default -- a taste assumption, not a fact).
    eff = {}
    for s in seed_slugs:
        bonus = CFG["seed_obscurity_bonus"] * (1 - popnorm(films[s].get("rating_count")))
        eff[s] = wmap[s] * (1 + bonus)

    # ---- channel: graph convergence -------------------------------------
    decay = CFG["graph_decay"]
    reach = collections.defaultdict(dict)
    sources = [(s, eff[s]) for s in seed_slugs] + list(pos_anchor.items())
    for s, w in sources:
        for n in films[s]["similar"]:
            reach[n][s] = max(reach[n].get(s, 0), w)
            for m in films.get(n, {}).get("similar", []):
                reach[m][s] = max(reach[m].get(s, 0), w * decay)
    # Negative reach: one hop only -- letterboxd's own "similar to the thing
    # you said never to" is direct evidence; two hops out it's just noise.
    neg_reach = collections.Counter()
    for s, w in neg_anchor.items():
        for n in films[s]["similar"]:
            neg_reach[n] += w

    # Shared-person edges. Repeat-seed decay (matches crawl.py): a person's
    # 2nd, 3rd... seed film confirms the affinity rather than multiplying it,
    # so a few prolific favorites can't drown out everyone else.
    rdecay = CFG["person_repeat_decay"]
    seed_people = collections.Counter()
    pname = {}
    repeats = collections.Counter()
    for s in seed_slugs:
        for p, nm in films[s]["directors"]:
            key = ("d", p)
            seed_people[p] += eff[s] * 1.0 * (rdecay ** repeats[key]); repeats[key] += 1
            pname[p] = nm
        for p, nm in films[s]["writers"]:
            key = ("w", p)
            seed_people[p] += eff[s] * 0.5 * (rdecay ** repeats[key]); repeats[key] += 1
            pname[p] = nm
        for i, (p, nm) in enumerate(films[s]["cast"][:12]):
            key = ("c", p)
            seed_people[p] += eff[s] * 0.45 * (0.85 ** i) * (rdecay ** repeats[key]); repeats[key] += 1
            pname[p] = nm
    for slug, boost in (CFG.get("person_boost") or {}).items():
        if slug in seed_people:
            seed_people[slug] += boost
    # People in nevers: same repeat decay, so one bad film by a favorite
    # tempers them; a run of nevers by one director cancels them out.
    neg_people = collections.Counter()
    nrep = collections.Counter()
    for s, w in neg_anchor.items():
        for p, _ in films[s]["directors"]:
            neg_people[p] += w * 1.0 * (rdecay ** nrep[p]); nrep[p] += 1
        for i, (p, _) in enumerate(films[s]["cast"][:4]):
            neg_people[p] += w * 0.3 * (0.85 ** i) * (rdecay ** nrep[p]); nrep[p] += 1

    # ---- channel: theme vector ------------------------------------------
    space = ThemeSpace(films, CFG["token_weights"])
    centroid = space.centroid((films[s], w) for s, w in sources)

    # What sets nevers apart from this pool, not what they share with it:
    # nevers were recommended for a reason, so their raw centroid overlaps
    # the pool's and penalising it would penalise the pool itself. Project
    # the shared direction out and keep the remainder. Nevers given in a
    # different pool count for less here -- a bad comedy says little about
    # which slow dramas to skip.
    neg_c = space.centroid(
        (films[s], w * (1.0 if neg_home.get(s) in (None, P.pool) else cross))
        for s, w in neg_anchor.items())
    overlap = dot(neg_c, centroid)
    neg_resid = unit({t: neg_c.get(t, 0) - overlap * centroid.get(t, 0)
                      for t in set(neg_c) | set(centroid)})

    # ---- assemble --------------------------------------------------------
    rows = []
    for slug, rec in films.items():
        if rec.get("dead") or slug in seedset:
            continue
        if common.is_junk(rec, CFG):
            continue

        g_detail = sorted(reach.get(slug, {}).items(), key=lambda kv: -kv[1])
        g_raw = max(0.0, sum(v for _, v in g_detail) - NEG["graph"] * neg_reach.get(slug, 0))

        tv = space.vec(rec)
        t_pos = dot(tv, centroid)
        t_neg = max(0.0, dot(tv, neg_resid))
        t_raw = max(0.0, t_pos - NEG["theme"] * t_neg)
        shared = sorted(((centroid.get(t, 0) * tv[t], t) for t in tv if t in centroid),
                        reverse=True)

        p_raw, p_detail = 0.0, []
        for p, nm in rec["directors"]:
            p_raw -= NEG["people"] * neg_people.get(p, 0)
            if seed_people.get(p):
                p_raw += seed_people[p] * 1.0
                p_detail.append("dir:" + nm)
        for p, nm in rec["writers"]:
            if seed_people.get(p):
                p_raw += seed_people[p] * 0.4
                p_detail.append("wri:" + nm)
        for i, (p, nm) in enumerate(rec["cast"][:12]):
            if seed_people.get(p):
                p_raw += seed_people[p] * 0.45 * (0.85 ** i)
                p_detail.append("cast:" + nm)
        for i, (p, _) in enumerate(rec["cast"][:4]):
            p_raw -= NEG["people"] * 0.3 * neg_people.get(p, 0) * (0.85 ** i)
        p_raw = math.log1p(max(0.0, p_raw))

        v, R = rec.get("rating_count") or 0, rec.get("rating") or 0
        m, C = CFG["bayes_prior_count"], CFG["bayes_prior_rating"]
        q_raw = (v * R + m * C) / (v + m) if (v + m) else C

        rows.append({"slug": slug, "rec": rec,
                     "g_raw": g_raw, "t_raw": t_raw, "p_raw": p_raw, "q_raw": q_raw,
                     "seeds": g_detail, "shared": shared[:6], "people": p_detail[:6]})

    g95 = pct([r["g_raw"] for r in rows], 95)
    t95 = pct([r["t_raw"] for r in rows], 95)
    p95 = pct([r["p_raw"] for r in rows], 95)
    qlo, qhi = 2.6, 4.35
    W = CFG["weights"]
    lo, hi = CFG["popularity_clamp"]
    lean = CFG.get("popularity_lean", 0.0)

    gate_floor = CFG.get("people_gate_floor", 1.0)
    for r in rows:
        r["g"] = min(1.25, r["g_raw"] / g95)
        r["t"] = min(1.25, r["t_raw"] / t95)
        # People only count in full when corroborated by graph or theme.
        rel = min(1.0, max(r["g"], r["t"]) / 0.8)
        gate = gate_floor + (1 - gate_floor) * rel
        r["p"] = min(1.25, r["p_raw"] / p95) * gate
        r["q"] = min(1.25, max(0.0, (r["q_raw"] - qlo) / (qhi - qlo)))
        cnt = r["rec"].get("rating_count") or 1
        r["pop_adj"] = min(hi, max(lo, 1.0 - lean * math.log10(cnt / float(CFG["popularity_pivot"]))))
        r["score"] = 100 * r["pop_adj"] * (
            W["graph"] * r["g"] + W["theme"] * r["t"]
            + W["people"] * r["p"] + W["quality"] * r["q"])
        r["already"] = r["slug"] in done

    rows.sort(key=lambda r: -r["score"])
    payload = {
        "profile": P.profile, "pool": P.pool,
        "seed_count": len(seed_slugs),
        "pool_size": len(films),
        "scored": len(rows),
        "people": [{"slug": p, "name": pname.get(p, p), "score": round(v, 3)}
                   for p, v in seed_people.most_common(40)],
        "films": [{
            "slug": r["slug"], "title": r["rec"].get("title"), "year": r["rec"].get("year"),
            "score": round(r["score"], 2),
            "channels": {k: round(r[k], 3) for k in ("g", "t", "p", "q")},
            "pop_adj": round(r["pop_adj"], 3),
            "rating": r["rec"].get("rating"), "rating_count": r["rec"].get("rating_count"),
            "genres": [n for _, n in r["rec"].get("genres") or []],
            "mini_themes": [n for _, n in r["rec"].get("mini_themes") or []],
            "directors": [n for _, n in r["rec"].get("directors") or []],
            "cast": [n for _, n in (r["rec"].get("cast") or [])[:6]],
            "via_seeds": [[films[s].get("title") or s, round(v, 3)] for s, v in r["seeds"][:6]],
            "shared_tokens": [t.split(":", 1)[1] for _, t in r["shared"]],
            "via_people": r["people"],
            "already_graded": r["already"],
            "imdb": r["rec"].get("imdb"), "tmdb": r["rec"].get("tmdb"),
            "poster": r["rec"].get("poster"), "synopsis": r["rec"].get("synopsis"),
            "runtime": r["rec"].get("runtime"),
            "cast_billed": r["rec"].get("cast_billed") or [n for _, n in (r["rec"].get("cast") or [])[:6]],
        } for r in rows],
    }
    os.makedirs(P.pool_dir, exist_ok=True)
    with open(P.scores, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
    print("[%s/%s] scored %d candidates from a pool of %d (seeds=%d, +%d liked anchors, "
          "%d never/disliked pushing away)"
          % (P.profile, P.pool, len(rows), len(films), len(seed_slugs), len(pos_anchor),
             len(neg_anchor)))
    for r in rows[:15]:
        print("  %6.2f  %-44s g=%.2f t=%.2f p=%.2f q=%.2f pop=%.2f"
              % (r["score"], common.label(r["rec"])[:44],
                 r["g"], r["t"], r["p"], r["q"], r["pop_adj"]))


if __name__ == "__main__":
    main()
