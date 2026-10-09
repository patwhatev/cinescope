"""Grade the recommender against your verdicts, and propose better weights.

Reads every verdict in out/grades.csv (see common.verdict): a seen film's
enjoyment rating and a `never` count at full weight, an unseen film's
want-to-see interest at half weight, an untriaged old grade at full weight.
Then:  python3 pipeline/tune.py [--apply]

Reports precision@k, per-channel discrimination, score calibration, and a
proposed reweighting. --apply writes the new weights into config.json.
"""
import collections
import csv
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

CH = ("g", "t", "p", "q")
NAMES = {"g": "graph", "t": "theme", "p": "people", "q": "quality"}


def pearson(xs, ys, ws=None):
    n = len(xs)
    if n < 3:
        return 0.0
    ws = ws or [1.0] * n
    tw = sum(ws)
    mx = sum(w * x for w, x in zip(ws, xs)) / tw
    my = sum(w * y for w, y in zip(ws, ys)) / tw
    num = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys))
    dx = math.sqrt(sum(w * (x - mx) ** 2 for w, x in zip(ws, xs)))
    dy = math.sqrt(sum(w * (y - my) ** 2 for w, y in zip(ws, ys)))
    return num / (dx * dy) if dx and dy else 0.0


def main():
    gpath = os.path.join(common.OUT, "grades.csv")
    if not os.path.exists(gpath):
        sys.exit("no grades.csv yet — run report.py first")
    with open(os.path.join(common.DATA, "scores.json"), encoding="utf-8") as fh:
        S = json.load(fh)
    byslug = {f["slug"]: f for f in S["films"]}
    dirnames = common.load_films()

    def fnum(v):
        try:
            return float(v) if v not in (None, "") else None
        except ValueError:
            return None

    # Every verdict, regardless of whether its channel snapshot survived --
    # a film promoted to a seed drops out of scores.json entirely, and
    # requiring a live byslug match here used to silently exclude exactly
    # the films you rated highest from "graded", "hit rate", even "seen +
    # rated" below. Those stats only need the verdict itself.
    all_rows = []
    with open(gpath, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            v = common.verdict(r)
            if not v:
                continue
            f = byslug.get(r["slug"])
            dirs = (f or {}).get("directors")
            if not dirs:
                rec = dirnames.get(r["slug"])
                dirs = [n for _, n in (rec.get("directors") or [])] if rec else []
            channels = {c: fnum(r.get(c)) for c in CH}
            if any(channels[c] is None for c in CH) and f:
                channels = f["channels"]
            score = fnum(r.get("score"))
            if score is None and f:
                score = f["score"]
            rank = int(r["rank"] or 0)
            all_rows.append({"rank": rank, "slug": r["slug"], "title": r["title"],
                             "val": v[1], "score": score, "channels": channels,
                             "kind": v[0], "weight": v[2], "dirs": dirs,
                             "has_channels": not any(channels[c] is None for c in CH)})
    if len(all_rows) < 5:
        sys.exit("only %d graded rows — grade at least ~15 for signal" % len(all_rows))

    all_rows.sort(key=lambda x: x["rank"])
    graded = len(all_rows)
    hits = [r for r in all_rows if r["val"] >= 4]
    print("=" * 66)
    print("CINESCOPE SCORECARD   (%d graded)" % graded)
    print("=" * 66)
    print("mean grade        %.2f / 5" % (sum(r["val"] for r in all_rows) / graded))
    print("hit rate (>=4)    %.0f%%  (%d/%d)" % (100.0 * len(hits) / graded, len(hits), graded))
    print("miss rate (<=2)   %.0f%%" % (100.0 * sum(1 for r in all_rows if r["val"] <= 2) / graded))
    kinds = {k: sum(1 for r in all_rows if r["kind"] == k)
             for k in ("rating", "interest", "never", "legacy")}
    print("seen + rated      %d  (%.0f%% — high is good targeting, bad novelty)"
          % (kinds["rating"], 100.0 * kinds["rating"] / graded))
    print("unseen interest   %d  (weighted %.1f)   never %d   untriaged old grade %d"
          % (kinds["interest"], common.INTEREST_WEIGHT, kinds["never"], kinds["legacy"]))
    seen_rows = [r for r in all_rows if r["kind"] == "rating"]
    if seen_rows:
        sr_hits = sum(1 for r in seen_rows if r["val"] >= 4)
        print("  of those, hit rate on SEEN+RATED alone: %.0f%%  (%d/%d) -- the real truth "
              "signal; the combined figure above dilutes it with never/interest guesses"
              % (100.0 * sr_hits / len(seen_rows), sr_hits, len(seen_rows)))
    print()

    for k in (10, 20, 40):
        sub = [r for r in all_rows if r["rank"] and r["rank"] <= k]
        if sub:
            print("precision@%-3d      %.0f%%  (%d of %d graded in top %d)"
                  % (k, 100.0 * sum(1 for r in sub if r["val"] >= 4) / len(sub),
                     sum(1 for r in sub if r["val"] >= 4), len(sub), k))
    print()

    # Everything below needs a valid g/t/p/q snapshot -- a promoted seed
    # whose own channel history was already lost to a now-fixed bug (see
    # pull_grades.py) can't contribute here, only to the stats above.
    rows = [r for r in all_rows if r["has_channels"]]
    skipped = graded - len(rows)
    if skipped:
        print("(%d graded film%s with no channel snapshot available -- excluded from "
              "correlation/calibration/weights below, still counted above)"
              % (skipped, "" if skipped == 1 else "s"))
        print()

    print("-- channel discrimination (corr with your grade) " + "-" * 17)
    grades_ = [r["val"] for r in rows]
    weights = [r["weight"] for r in rows]
    corrs = {}
    for c in CH:
        corrs[c] = pearson([r["channels"][c] for r in rows], grades_, weights)
        bar = "#" * int(abs(corrs[c]) * 30)
        print("  %-8s r=%+.3f  %s" % (NAMES[c], corrs[c], bar))
    print("  %-8s r=%+.3f" % ("SCORE", pearson([r["score"] for r in rows], grades_, weights)))
    print()

    print("-- calibration (does a higher score mean a better film for you?) --")
    srt = sorted(rows, key=lambda r: -r["score"])
    third = max(1, len(srt) // 3)
    for lbl, sub in (("top third   ", srt[:third]), ("middle third", srt[third:2 * third]),
                     ("bottom third", srt[2 * third:])):
        if sub:
            print("  %s  mean grade %.2f   score range %.1f-%.1f"
                  % (lbl, sum(r["val"] for r in sub) / len(sub),
                     min(r["score"] for r in sub), max(r["score"] for r in sub)))
    print()

    cfg = common.config()
    old = cfg["weights"]
    lam = 0.6
    prop = {}
    for c in CH:
        prop[NAMES[c]] = max(0.02, old[NAMES[c]] * (1 + lam * corrs[c]))
    tot = sum(prop.values())
    prop = {k: round(v / tot, 3) for k, v in prop.items()}
    print("-- proposed weights " + "-" * 45)
    for k in old:
        arrow = "->" if abs(prop[k] - old[k]) > 0.005 else "  "
        print("  %-8s %.3f %s %.3f" % (k, old[k], arrow, prop[k]))
    print()

    print("-- worst misses (retune targets) " + "-" * 32)
    for r in sorted(rows, key=lambda x: (x["val"], -x["score"]))[:6]:
        if r["val"] <= 2:
            print("  %-8s %.0f  score %5.1f  %-38s %s" % (
                r["kind"], r["val"], r["score"], r["title"][:38],
                " ".join("%s=%.2f" % (c, r["channels"][c]) for c in CH)))
    print()
    print("-- promote to seeds (seen, rated 5) " + "-" * 29)
    for r in all_rows:
        if r["val"] >= 5 and r["kind"] in ("rating", "legacy"):
            print("  %-34s | 1.0 | from iteration grading" % r["slug"])
    print()

    print("-- director concentration in what you've graded " + "-" * 18)
    dirs_count = collections.Counter()
    for r in all_rows:
        for name in r["dirs"]:
            dirs_count[name] += 1
    top_dirs = dirs_count.most_common(6)
    uniq = len(dirs_count)
    concentrated = sum(n for _, n in top_dirs)
    print("  %d distinct directors across %d graded films" % (uniq, graded))
    if top_dirs:
        print("  top 6 account for %d films (%.0f%% of graded): %s"
              % (concentrated, 100.0 * concentrated / graded,
                 ", ".join("%s x%d" % (n, c) for n, c in top_dirs)))

    if "--apply" in sys.argv:
        cfg["weights"] = prop
        with open(os.path.join(common.ROOT, "config.json"), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        print("\napplied new weights to config.json — re-run score.py + report.py")


if __name__ == "__main__":
    main()
