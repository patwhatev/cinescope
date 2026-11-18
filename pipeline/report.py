"""Render scores.json into a readable report plus a grading sheet."""
import collections
import csv
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

P = common.paths()
CFG = common.config(P.pool)
TOP = int(os.environ.get("TOP", "40"))


def confidence(ch):
    strong = sum(1 for k in ("g", "t", "p", "q") if ch[k] >= 0.45)
    return {4: "high", 3: "high", 2: "medium"}.get(strong, "low")


def why(f):
    bits = []
    if f["via_seeds"]:
        names = ", ".join(s for s, _ in f["via_seeds"][:3])
        bits.append("converges from %d seeds (%s)" % (len(f["via_seeds"]), names))
    if f["shared_tokens"]:
        bits.append("shares: %s" % "; ".join(f["shared_tokens"][:2]).lower())
    if f["via_people"]:
        bits.append("people: %s" % ", ".join(f["via_people"][:2]))
    return " · ".join(bits) or "theme-vector match only"


def main():
    with open(P.scores, encoding="utf-8") as fh:
        S = json.load(fh)
    films = [f for f in S["films"] if not f["already_graded"]]
    itr = os.environ.get("ITER") or common.next_iteration(P.reports)
    L = []
    w = L.append

    w("# Cinescope — %s / %s — iteration %s" % (P.profile, P.pool, itr))
    w("")
    w("**%d films** crawled from letterboxd · **%d** scored as candidates · "
      "**%d seeds** in this pool." % (S["pool_size"], S["scored"], S["seed_count"]))
    w("")
    w("Channel weights: " + ", ".join("`%s %.2f`" % (k, v)
                                      for k, v in CFG["weights"].items()))
    w("")
    w("`g` graph convergence · `t` theme-vector cosine · `p` people overlap · "
      "`q` shrunk rating · `pop` popularity adjustment (from `popularity_lean`; "
      "1.00 = no tilt).")
    w("")

    w("## Top %d" % TOP)
    w("")
    for i, f in enumerate(films[:TOP], 1):
        c = f["channels"]
        w("**%d. %s (%s)** — %.1f · %s confidence" % (
            i, f["title"], f["year"], f["score"], confidence(c)))
        w("  ")
        w("%s  " % why(f))
        w("`g %.2f · t %.2f · p %.2f · q %.2f · pop %.2f` · "
          "letterboxd %s from %s ratings · %s  " % (
              c["g"], c["t"], c["p"], c["q"], f["pop_adj"],
              f["rating"], "{:,}".format(f["rating_count"] or 0),
              ", ".join(f["genres"]) or "—"))
        w("dir. %s · https://letterboxd.com/film/%s/" % (
            ", ".join(f["directors"]) or "—", f["slug"]))
        w("")

    # Bucket each film under its rarest genre so everything does not pile
    # into "Drama".
    gdf = collections.Counter()
    for f in films:
        for g in f["genres"]:
            gdf[g] += 1
    buckets = collections.defaultdict(list)
    for f in films[:150]:
        if not f["genres"]:
            buckets["Unclassified"].append(f)
            continue
        buckets[min(f["genres"], key=lambda g: gdf[g])].append(f)

    w("## By genre")
    w("")
    for g in sorted(buckets, key=lambda k: -sum(x["score"] for x in buckets[k][:5])):
        rows = buckets[g][:8]
        if not rows:
            continue
        w("### %s" % g)
        w("")
        for f in rows:
            w("- **%s (%s)** — %.1f · %s · dir. %s" % (
                f["title"], f["year"], f["score"],
                (f["mini_themes"] or ["—"])[0], ", ".join(f["directors"]) or "—"))
        w("")

    w("## People to explore")
    w("")
    w("Affinity = how strongly this pool's seeds over-represent this person "
      "(director 1.0, writer 0.5, cast 0.45 decayed by billing).")
    w("")
    byslug = {f["slug"]: f for f in films}
    for p in S["people"][:14]:
        picks = [f for f in films
                 if p["name"] in f["directors"] or p["name"] in f["cast"]][:4]
        if not picks:
            continue
        w("**%s** — affinity %.2f" % (p["name"], p["score"]))
        for f in picks:
            w("- %s (%s) — %.1f · dir. %s" % (f["title"], f["year"], f["score"],
                                              ", ".join(f["directors"]) or "—"))
        w("")

    # Films the similarity graph barely reaches but whose taste vector is a
    # strong match: the discoveries a pure co-occurrence model would miss.
    wild = sorted((f for f in films if f["channels"]["g"] < 0.22
                   and f["channels"]["t"] >= 0.5), key=lambda f: -f["channels"]["t"])
    if wild:
        w("## Wildcards")
        w("")
        w("Weak graph convergence, strong taste-vector match — what pure "
          "co-occurrence would have missed.")
        w("")
        for f in wild[:12]:
            w("- **%s (%s)** — t %.2f · %s · dir. %s" % (
                f["title"], f["year"], f["channels"]["t"],
                (f["mini_themes"] or ["—"])[0], ", ".join(f["directors"]) or "—"))
        w("")

    os.makedirs(P.reports, exist_ok=True)
    path = os.path.join(P.reports, "iteration-%s.md" % itr)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")

    gpath = P.grades_csv
    existing = {}
    if os.path.exists(gpath):
        with open(gpath, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                existing[row["slug"]] = row
    cols = common.GRADE_COLS
    with open(gpath, "w", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        rank = 0
        top_slugs = {f["slug"] for f in S["films"][:TOP]}
        for f in S["films"][:TOP]:
            rank += 1
            old = existing.get(f["slug"], {})
            c = f["channels"]
            row = {k: old.get(k, "") for k in cols}
            row.update({"rank": rank, "slug": f["slug"], "title": f["title"],
                        "year": f["year"], "score": f["score"], "pool": P.pool,
                        "g": c["g"], "t": c["t"], "p": c["p"], "q": c["q"]})
            wr.writerow(row)
        # keep any rows you already graded that are no longer in the top slice
        for slug, old in existing.items():
            if slug not in top_slugs and (common.verdict(old) or old.get("seen")):
                wr.writerow({k: old.get(k, "") for k in cols})

    print("wrote %s" % path)
    print("wrote %s" % gpath)


if __name__ == "__main__":
    main()
