"""Grade the recommender against your verdicts, and propose better weights.

Reads every verdict in out/grades.csv (see common.verdict): a seen film's
enjoyment rating and a `never` count at full weight, an unseen film's
want-to-see interest at half weight, an untriaged old grade at full weight.
Then:  python3 pipeline/tune.py [--apply]

Reports precision@k, per-channel discrimination, score calibration, and a
proposed reweighting. --apply writes the new weights into config.json.
"""
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

    rows = []
    with open(gpath, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            v = common.verdict(r)
            f = byslug.get(r["slug"])
            if not v or not f:
                continue
            rows.append((int(r["rank"] or 0), r["slug"], r["title"], v[1],
                         f["score"], f["channels"], v[0], v[2]))
    if len(rows) < 5:
        sys.exit("only %d graded rows — grade at least ~15 for signal" % len(rows))

    rows.sort(key=lambda x: x[0])
    graded = len(rows)
    hits = [r for r in rows if r[3] >= 4]
    print("=" * 66)
    print("CINESCOPE SCORECARD   (%d graded)" % graded)
    print("=" * 66)
    print("mean grade        %.2f / 5" % (sum(r[3] for r in rows) / graded))
    print("hit rate (>=4)    %.0f%%  (%d/%d)" % (100.0 * len(hits) / graded,
                                                 len(hits), graded))
    print("miss rate (<=2)   %.0f%%" % (100.0 * sum(1 for r in rows if r[3] <= 2) / graded))
    kinds = {k: sum(1 for r in rows if r[6] == k)
             for k in ("rating", "interest", "never", "legacy")}
    print("seen + rated      %d  (%.0f%% — high is good targeting, bad novelty)"
          % (kinds["rating"], 100.0 * kinds["rating"] / graded))
    print("unseen interest   %d  (weighted %.1f)   never %d   untriaged old grade %d"
          % (kinds["interest"], common.INTEREST_WEIGHT, kinds["never"], kinds["legacy"]))
    print()

    for k in (10, 20, 40):
        sub = [r for r in rows if r[0] and r[0] <= k]
        if sub:
            print("precision@%-3d      %.0f%%  (%d of %d graded in top %d)"
                  % (k, 100.0 * sum(1 for r in sub if r[3] >= 4) / len(sub),
                     sum(1 for r in sub if r[3] >= 4), len(sub), k))
    print()

    print("-- channel discrimination (corr with your grade) " + "-" * 17)
    grades = [r[3] for r in rows]
    weights = [r[7] for r in rows]
    corrs = {}
    for c in CH:
        corrs[c] = pearson([r[5][c] for r in rows], grades, weights)
        bar = "#" * int(abs(corrs[c]) * 30)
        print("  %-8s r=%+.3f  %s" % (NAMES[c], corrs[c], bar))
    print("  %-8s r=%+.3f" % ("SCORE", pearson([r[4] for r in rows], grades, weights)))
    print()

    print("-- calibration (does a higher score mean a better film for you?) --")
    srt = sorted(rows, key=lambda r: -r[4])
    third = max(1, len(srt) // 3)
    for lbl, sub in (("top third   ", srt[:third]), ("middle third", srt[third:2 * third]),
                     ("bottom third", srt[2 * third:])):
        if sub:
            print("  %s  mean grade %.2f   score range %.1f-%.1f"
                  % (lbl, sum(r[3] for r in sub) / len(sub),
                     min(r[4] for r in sub), max(r[4] for r in sub)))
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
    for r in sorted(rows, key=lambda x: (x[3], -x[4]))[:6]:
        if r[3] <= 2:
            print("  %-8s %.0f  score %5.1f  %-38s %s" % (
                r[6], r[3], r[4], r[2][:38],
                " ".join("%s=%.2f" % (c, r[5][c]) for c in CH)))
    print()
    print("-- promote to seeds (seen, rated 5) " + "-" * 29)
    for r in rows:
        if r[3] >= 5 and r[6] in ("rating", "legacy"):
            print("  %-34s | 1.0 | from iteration grading" % r[1])

    if "--apply" in sys.argv:
        cfg["weights"] = prop
        with open(os.path.join(common.ROOT, "config.json"), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        print("\napplied new weights to config.json — re-run score.py + report.py")


if __name__ == "__main__":
    main()
