"""Score every crawled film against the seed profile.

Four independent channels, each normalised by its own 95th percentile so the
config weights mean what they say and stay comparable when tuning:

  graph    how many of your seeds converge on this film, decayed by distance.
           This is the co-occurrence signal: letterboxd's similarity edges are
           themselves distilled from list/rating overlap, so breadth of seed
           convergence is the thing being measured, not raw edge count.
  theme    cosine between the film's idf-weighted theme vector and the centroid
           of your seeds. Mini-themes carry the taste shape; genre is coarse.
  people   director/writer/cast overlap with the people your seeds over-represent.
  quality  letterboxd rating, shrunk toward the global mean by rating count.

A popularity adjustment then damps films so canonical they sit adjacent to
everything, and lifts the deep cuts, because that is where this profile lives.
"""
import collections
import csv
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

CFG = common.config()


def pct(values, p):
    if not values:
        return 1.0
    xs = sorted(values)
    i = min(len(xs) - 1, max(0, int(round(p / 100.0 * (len(xs) - 1)))))
    return xs[i] or 1.0


def tokens(rec, tw):
    out = {}
    for key, w in (("mini_themes", tw["mini_theme"]), ("themes", tw["theme"]),
                   ("genres", tw["genre"])):
        for slug, name in rec.get(key) or []:
            out["%s:%s" % (key, slug)] = max(out.get("%s:%s" % (key, slug), 0), w)
    return out


def unit(vec):
    n = math.sqrt(sum(v * v for v in vec.values()))
    return {k: v / n for k, v in vec.items()} if n else {}


def popnorm(count):
    if not count:
        return 0.0
    return min(1.0, max(0.0, (math.log10(count) - 3.5) / 3.0))


def graded():
    """Films you have already judged — excluded from new recommendations."""
    path = os.path.join(common.OUT, "grades.csv")
    out = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                g = (row.get("grade") or "").strip()
                seen = (row.get("seen") or "").strip().lower() in ("y", "yes", "1", "true")
                if g or seen:
                    out[row["slug"]] = {"grade": float(g) if g else None, "seen": seen}
    return out


def main():
    films = common.load_films()
    seedlist = common.seeds()
    wmap = dict(seedlist)
    seed_slugs = [s for s, _ in seedlist if s in films]
    tw = CFG["token_weights"]
    done = graded()

    # Seeds you rate more obscurely are more diagnostic of idiosyncratic taste,
    # so they pull harder than the canon entries everybody has seen.
    eff = {}
    for s in seed_slugs:
        bonus = CFG["seed_obscurity_bonus"] * (1 - popnorm(films[s].get("rating_count")))
        eff[s] = wmap[s] * (1 + bonus)

    # ---- channel: graph convergence -------------------------------------
    decay = CFG["graph_decay"]
    reach = collections.defaultdict(dict)
    for s in seed_slugs:
        for n in films[s]["similar"]:
            reach[n][s] = max(reach[n].get(s, 0), eff[s])
            for m in films.get(n, {}).get("similar", []):
                reach[m][s] = max(reach[m].get(s, 0), eff[s] * decay)
    # Shared-person edges extend reach to filmography films no seed points at.
    seed_people = collections.Counter()
    pname = {}
    for s in seed_slugs:
        for p, nm in films[s]["directors"]:
            seed_people[p] += eff[s] * 1.0
            pname[p] = nm
        for p, nm in films[s]["writers"]:
            seed_people[p] += eff[s] * 0.5
            pname[p] = nm
        for i, (p, nm) in enumerate(films[s]["cast"][:12]):
            seed_people[p] += eff[s] * 0.45 * (0.85 ** i)
            pname[p] = nm
    for slug, boost in CFG["person_boost"].items():
        if slug in seed_people:
            seed_people[slug] += boost

    # ---- channel: theme vector ------------------------------------------
    corpus = [r for r in films.values() if not r.get("dead")]
    df = collections.Counter()
    for r in corpus:
        for t in tokens(r, tw):
            df[t] += 1
    N = max(1, len(corpus))
    idf = {t: math.log(1 + N / (1 + d)) for t, d in df.items()}

    centroid = collections.defaultdict(float)
    for s in seed_slugs:
        v = unit({t: w * idf.get(t, 1.0) for t, w in tokens(films[s], tw).items()})
        for t, val in v.items():
            centroid[t] += eff[s] * val
    centroid = unit(centroid)

    # ---- assemble --------------------------------------------------------
    rows = []
    for slug, rec in films.items():
        if rec.get("dead") or slug in seed_slugs:
            continue
        if common.is_junk(rec, CFG["min_rating_count"]):
            continue

        g_detail = sorted(reach.get(slug, {}).items(), key=lambda kv: -kv[1])
        g_raw = sum(v for _, v in g_detail)

        tv = unit({t: w * idf.get(t, 1.0) for t, w in tokens(rec, tw).items()})
        t_raw = sum(tv.get(t, 0) * centroid.get(t, 0) for t in tv)
        shared = sorted(((centroid.get(t, 0) * tv[t], t) for t in tv if t in centroid),
                        reverse=True)

        p_raw, p_detail = 0.0, []
        for p, nm in rec["directors"]:
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
        p_raw = math.log1p(p_raw)

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

    for r in rows:
        r["g"] = min(1.25, r["g_raw"] / g95)
        r["t"] = min(1.25, r["t_raw"] / t95)
        r["p"] = min(1.25, r["p_raw"] / p95)
        r["q"] = min(1.25, max(0.0, (r["q_raw"] - qlo) / (qhi - qlo)))
        cnt = r["rec"].get("rating_count") or 1
        r["pop_adj"] = min(hi, max(lo, 1.0 - CFG["popularity_slope"]
                                   * math.log10(cnt / float(CFG["popularity_pivot"]))))
        r["score"] = 100 * r["pop_adj"] * (
            W["graph"] * r["g"] + W["theme"] * r["t"]
            + W["people"] * r["p"] + W["quality"] * r["q"])
        r["already"] = r["slug"] in done

    rows.sort(key=lambda r: -r["score"])
    payload = {
        "seed_count": len(seed_slugs),
        "pool": len(films),
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
    os.makedirs(common.DATA, exist_ok=True)
    with open(os.path.join(common.DATA, "scores.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
    print("scored %d candidates from a pool of %d (seeds=%d)"
          % (len(rows), len(films), len(seed_slugs)))
    for r in rows[:15]:
        print("  %6.2f  %-44s g=%.2f t=%.2f p=%.2f q=%.2f pop=%.2f"
              % (r["score"], common.label(r["rec"])[:44],
                 r["g"], r["t"], r["p"], r["q"], r["pop_adj"]))


if __name__ == "__main__":
    main()
