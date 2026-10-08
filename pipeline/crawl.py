"""Build the candidate pool from letterboxd's film graph.

Four phases, each cached on disk so re-runs are nearly free:
  1. seeds
  2. every film the seeds point at           (depth 1)
  3. metadata for the strongest depth-2 films
  4. filmographies of the people the seeds over-represent, then their films
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import fetch
import parse

CFG = common.config()


def grab(slug, films, note=""):
    if slug in films:
        return films[slug]
    page = fetch.film_page(slug)
    if not page:
        films[slug] = {"slug": slug, "title": slug, "year": "", "dead": True,
                       "similar": [], "genres": [], "themes": [], "mini_themes": [],
                       "directors": [], "writers": [], "cast": [],
                       "rating": None, "rating_count": 0}
        return films[slug]
    rec = parse.film(slug, page)
    films[slug] = rec
    print("    + %-46s %s" % (rec["slug"], note), flush=True)
    return rec


def person_films(kind, slug):
    import re
    page = fetch.person_page(kind, slug)
    if not page:
        return []
    seen, out = set(), []
    for s in re.findall(r'data-item-slug="([a-z0-9\-]+)"', page):
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def main():
    films = common.load_films()
    seedlist = common.seeds()
    seed_slugs = [s for s, _ in seedlist]
    wmap = dict(seedlist)

    print("phase 1: %d seeds" % len(seed_slugs), flush=True)
    for s in seed_slugs:
        grab(s, films, "(seed)")

    print("phase 2: depth-1 neighbours", flush=True)
    depth1 = []
    for s in seed_slugs:
        for n in films[s]["similar"]:
            if n not in seed_slugs and n not in depth1:
                depth1.append(n)
    print("  %d unique" % len(depth1), flush=True)
    for n in depth1:
        grab(n, films, "(d1)")

    print("phase 3: depth-2 convergence", flush=True)
    # Preliminary score: how many seeds reach this film, decayed by distance.
    reach = collections.defaultdict(dict)
    for s in seed_slugs:
        w = wmap[s]
        for n in films[s]["similar"]:
            reach[n][s] = max(reach[n].get(s, 0), w)
        for n in films[s]["similar"]:
            for m in films.get(n, {}).get("similar", []):
                reach[m][s] = max(reach[m].get(s, 0), w * CFG["graph_decay"])
    prelim = sorted(((sum(v.values()), k) for k, v in reach.items()
                     if k not in seed_slugs and k not in films),
                    reverse=True)
    budget = CFG["crawl"]["depth2_metadata_budget"]
    print("  %d unfetched candidates, taking top %d" % (len(prelim), budget), flush=True)
    for _, slug in prelim[:budget]:
        grab(slug, films, "(d2)")

    print("phase 4: people expansion", flush=True)
    aff = collections.Counter()
    role = {}
    for s in seed_slugs:
        rec, w = films[s], wmap[s]
        for p, name in rec["directors"]:
            aff[("director", p)] += w * 1.0
            role[p] = name
        for p, name in rec["writers"]:
            aff[("writer", p)] += w * 0.5
            role[p] = name
        for i, (p, name) in enumerate(rec["cast"][:12]):
            aff[("actor", p)] += w * 0.45 * (0.85 ** i)
            role[p] = name
    for slug, boost in CFG["person_boost"].items():
        for kind in ("director", "actor"):
            if (kind, slug) in aff:
                aff[(kind, slug)] += boost
    top = [kv for kv in aff.most_common() if kv[1] >= 0.5][:CFG["crawl"]["person_count"]]
    print("  top people: %s" % ", ".join("%s(%s,%.2f)" % (role.get(p, p), k[:3], v)
                                         for (k, p), v in top), flush=True)
    pool = collections.Counter()
    for (kind, p), v in top:
        for f in person_films(kind, p):
            if f not in seed_slugs:
                pool[f] += v
    fresh = [(v, f) for f, v in pool.items() if f not in films]
    fresh.sort(reverse=True)
    pbudget = CFG["crawl"]["person_film_budget"]
    print("  %d new films from filmographies, taking top %d"
          % (len(fresh), pbudget), flush=True)
    for _, f in fresh[:pbudget]:
        grab(f, films, "(person)")

    common.save_films(films)
    with open(os.path.join(common.DATA, "people.json"), "w", encoding="utf-8") as fh:
        json.dump({"affinity": [{"kind": k, "slug": p, "name": role.get(p, p),
                                 "score": round(v, 3)}
                                for (k, p), v in aff.most_common(60)]},
                  fh, indent=1, ensure_ascii=False)
    print("done: %d films in pool" % len(films), flush=True)


if __name__ == "__main__":
    main()
