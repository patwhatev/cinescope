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
import pools

P = common.paths()
CFG = common.config(P.pool)


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
    seedlist = common.read_seeds(P.seeds)
    if not seedlist:
        sys.exit("pool %r has no seeds yet -- add some to %s" % (P.pool, P.seeds))
    seed_slugs = [s for s, _ in seedlist]
    wmap = dict(seedlist)

    print("[%s/%s] phase 1: %d seeds" % (P.profile, P.pool, len(seed_slugs)), flush=True)
    for s in seed_slugs:
        grab(s, films, "(seed)")
    seed_slugs = [s for s in seed_slugs if not films[s].get("dead")]

    # Every graded film in the profile needs metadata before pools can be
    # told apart (a letterboxd import, say, is mostly films the crawl has
    # never reached) -- fetch them first, then work out which are this
    # pool's anchors.
    rows = common.read_db_grades(P.profile)
    for s in rows:
        if s not in films:
            grab(s, films, "(graded)")
    assignment = pools.assign(P.profile, rows, films)
    # This pool's hits widen the graph walk (lighter than seeds); this is
    # what turns "around the seeds" into a constellation.
    pos_anchor, neg_anchor, _ = common.anchors(P.pool, P.profile, assignment)
    anchor_slugs = [s for s in pos_anchor if not films[s].get("dead") and s not in wmap]
    sources = seed_slugs + anchor_slugs
    wmap = dict(wmap, **{s: pos_anchor[s] for s in anchor_slugs})

    print("phase 2: depth-1 neighbours (%d seeds + %d liked anchors)"
          % (len(seed_slugs), len(anchor_slugs)), flush=True)
    depth1 = []
    for s in sources:
        for n in films[s]["similar"]:
            if n not in sources and n not in depth1:
                depth1.append(n)
    print("  %d unique" % len(depth1), flush=True)
    for n in depth1:
        grab(n, films, "(d1)")

    print("phase 3: depth-2 convergence", flush=True)
    # Preliminary score: how many seeds reach this film, decayed by distance.
    reach = collections.defaultdict(dict)
    for s in sources:
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
    # Repeat-seed decay: a person's 2nd, 3rd... seed film is confirming
    # evidence, not a fresh multiplier -- without this, four seeds by one
    # director gave them 4x a single-seed director's crawl priority, which
    # is how one or two prolific favorites end up burying everyone else's
    # filmography in budget. Each person's own repeat count decays
    # independently, cast/writer/director each have their own counter.
    decay = CFG.get("person_repeat_decay", 0.3)
    aff = collections.Counter()
    role = {}
    repeats = collections.Counter()
    for s in seed_slugs:
        rec, w = films[s], wmap[s]
        for p, name in rec["directors"]:
            key = ("director", p)
            aff[key] += w * 1.0 * (decay ** repeats[key]); repeats[key] += 1
            role[p] = name
        for p, name in rec["writers"]:
            key = ("writer", p)
            aff[key] += w * 0.5 * (decay ** repeats[key]); repeats[key] += 1
            role[p] = name
        for i, (p, name) in enumerate(rec["cast"][:12]):
            key = ("actor", p)
            aff[key] += w * 0.45 * (0.85 ** i) * (decay ** repeats[key]); repeats[key] += 1
            role[p] = name
    for slug, boost in (CFG.get("person_boost") or {}).items():
        for kind in ("director", "actor"):
            if (kind, slug) in aff:
                aff[(kind, slug)] += boost
    # Directors of your nevers lose crawl priority the same way score.py
    # penalises them, so their filmographies stop eating the budget.
    neg_dir, nrep = collections.Counter(), collections.Counter()
    for s, w in neg_anchor.items():
        for p, _ in (films.get(s) or {}).get("directors") or []:
            neg_dir[p] += w * (decay ** nrep[p]); nrep[p] += 1
    for (kind, p) in list(aff):
        if kind == "director" and neg_dir.get(p):
            aff[(kind, p)] -= CFG.get("never_penalty", {}).get("people", 0.6) * neg_dir[p]
    top = [kv for kv in aff.most_common() if kv[1] >= 0.5][:CFG["crawl"]["person_count"]]
    print("  top people: %s" % ", ".join("%s(%s,%.2f)" % (role.get(p, p), k[:3], v)
                                         for (k, p), v in top), flush=True)

    # Opportunity people: a single strong hit in last run's scored pool,
    # not already a seed or already covered above, whose filmography has
    # never been explored -- the other side of the same fix, spending some
    # of the budget freed up on genuine discovery instead of more of the
    # same favorites. Needs a prior scores.json for this pool; the first
    # crawl has none yet and simply skips this.
    opp_n = CFG["crawl"].get("opportunity_count", 0)
    opp_min = CFG["crawl"].get("opportunity_min_score", 1e9)
    prev_path = P.scores
    if opp_n and os.path.exists(prev_path):
        with open(prev_path, encoding="utf-8") as fh:
            prev = json.load(fh)
        seed_dir_names = {name for s in seed_slugs for _, name in films[s]["directors"]}
        covered_names = {role.get(p, p) for _, p in top}
        name_to_slug = {}
        for rec in films.values():
            for pslug, name in rec.get("directors") or []:
                name_to_slug.setdefault(name, pslug)
        by_name = collections.defaultdict(list)
        for f in prev["films"]:
            for name in f["directors"]:
                by_name[name].append(f)
        singles = [(max(fs, key=lambda x: x["score"]), name)
                  for name, fs in by_name.items() if len(fs) == 1]
        singles.sort(key=lambda x: -x[0]["score"])
        added = []
        for f, name in singles:
            if f["score"] < opp_min or len(added) >= opp_n:
                break
            if name in seed_dir_names or name in covered_names:
                continue
            pslug = name_to_slug.get(name)
            if pslug:
                top.append((("director", pslug), 0.6))
                added.append("%s(%.1f)" % (name, f["score"]))
        if added:
            print("  opportunity directors (single strong hit, never explored): %s"
                  % ", ".join(added), flush=True)

    # Per-person cap before the global budget cut: bounds how much of any
    # one person's catalog can dominate the pool regardless of how their
    # affinity score compares to everyone else's.
    pcap = CFG["crawl"].get("person_cap_per_crawl")
    pool = collections.Counter()
    for (kind, p), v in top:
        person_slugs = person_films(kind, p)
        for f in person_slugs[:pcap] if pcap else person_slugs:
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
    os.makedirs(P.pool_dir, exist_ok=True)
    with open(P.people, "w", encoding="utf-8") as fh:
        json.dump({"affinity": [{"kind": k, "slug": p, "name": role.get(p, p),
                                 "score": round(v, 3)}
                                for (k, p), v in aff.most_common(60)]},
                  fh, indent=1, ensure_ascii=False)
    print("done: %d films in pool" % len(films), flush=True)


if __name__ == "__main__":
    main()
