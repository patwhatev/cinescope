"""Grade one pool's recommender against your verdicts, and propose better weights.

Reads every verdict in the pool's grades.csv (see common.verdict): a seen
film's enjoyment rating and a `never` count at full weight, an unseen film's
want-to-see interest at the weight the profile's scale gives it, an
untriaged old grade at full weight. Then:  python3 pipeline/tune.py [--apply]

Reports precision@k, per-channel discrimination, score calibration, and a
proposed reweighting. --apply writes the new weights into this pool's
settings in profile.json -- but only once the pool has `tune.min_rows`
graded films with channel snapshots; below that the pool keeps inheriting
the profile / default weights rather than chasing noise.
"""
import collections
import csv
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

P = common.paths()
SC = common.scale(common.config(P.pool))
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


def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2.0
        i = j + 1
    return out


def spearman(xs, ys):
    return pearson(ranks(xs), ranks(ys))


CROWD_TIERS = ((0.0, 2.8), (2.8, 3.5), (3.5, 5.01))


def crowd_agreement(all_rows, films):
    """Does letterboxd's average rating track your own taste? Measured on
    films you've watched -- the only clean labels: the cards show the
    letterboxd rating while you triage, so want-to-see/never verdicts are
    partly the crowd's opinion echoed back (the interest row shows how much).
    Re-check before leaning on the quality channel or any crowd-rating gate."""
    print("-- crowd agreement (your ratings vs letterboxd average) " + "-" * 10)
    seen, triage = [], []
    for r in all_rows:
        rec = films.get(r["slug"]) or {}
        lb = rec.get("rating")
        if not lb:
            continue
        if r["kind"] == "rating":
            seen.append((float(lb), r["val"], r))
        elif r["kind"] in ("interest", "never"):
            triage.append((float(lb), r["val"]))
    if len(seen) < 10:
        print("  only %d seen+rated films with a letterboxd rating — too few to judge" % len(seen))
        return
    rho = spearman([x for x, _, _ in seen], [y for _, y, _ in seen])
    print("  seen + rated   n=%-4d spearman %+.3f   <- the real test" % (len(seen), rho))
    if len(triage) >= 10:
        print("  triage labels  n=%-4d spearman %+.3f   (crowd rating was on screen)"
              % (len(triage), spearman([x for x, _ in triage], [y for _, y in triage])))
    for lo, hi in CROWD_TIERS:
        t = [y for x, y, _ in seen if lo <= x < hi]
        if t:
            print("  letterboxd %.1f-%.1f  n=%-3d your mean %.2f  liked(%d+) %3.0f%%"
                  % (lo, min(hi, 5.0), len(t), sum(t) / len(t), SC["hit_min"],
                     100.0 * sum(y >= SC["hit_min"] for y in t) / len(t)))
    below = [(x, y, r) for x, y, r in seen if y >= SC["hit_min"] and x < CROWD_TIERS[2][0]]
    if below:
        themes = collections.Counter()
        for _, _, r in below:
            for _, n in (films.get(r["slug"]) or {}).get("mini_themes") or []:
                themes[n] += 1
        print("  liked despite the crowd (<%.1f): %d — %s"
              % (CROWD_TIERS[2][0], len(below), ", ".join(
                  "%s %.1f" % (r["title"], x) for x, _, r in sorted(below, key=lambda b: b[0])[:8])))
        if themes:
            print("    common themes: %s" % ", ".join("%s x%d" % kv for kv in themes.most_common(3)))
    if rho < 0.15:
        print("  verdict: the crowd does NOT predict what you enjoy — keep quality low, no rating floor")
    else:
        print("  verdict: the crowd tracks your taste (rho %.2f) — a quality boost / floor is worth a holdout test" % rho)


def main():
    gpath = P.grades_csv
    if not os.path.exists(gpath) or not os.path.exists(P.scores):
        print("[%s/%s] nothing to tune yet (no grades.csv / scores.json)" % (P.profile, P.pool))
        return
    with open(P.scores, encoding="utf-8") as fh:
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
            v = common.verdict(r, SC)
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
        print("[%s/%s] only %d graded rows — grade at least ~15 for signal"
              % (P.profile, P.pool, len(all_rows)))
        return

    all_rows.sort(key=lambda x: x["rank"])
    graded = len(all_rows)
    hits = [r for r in all_rows if r["val"] >= SC["hit_min"]]
    print("=" * 66)
    print("CINESCOPE SCORECARD   %s / %s   (%d graded)" % (P.profile, P.pool, graded))
    print("=" * 66)
    print("mean grade        %.2f / 5" % (sum(r["val"] for r in all_rows) / graded))
    print("hit rate (>=%d)    %.0f%%  (%d/%d)" % (SC["hit_min"], 100.0 * len(hits) / graded, len(hits), graded))
    print("miss rate (<=%d or never)   %.0f%%" % (SC["miss_max"], 100.0 * sum(
        1 for r in all_rows if r["val"] <= SC["miss_max"]) / graded))
    kinds = {k: sum(1 for r in all_rows if r["kind"] == k)
             for k in ("rating", "interest", "never", "legacy")}
    print("seen + rated      %d  (%.0f%% — high is good targeting, bad novelty)"
          % (kinds["rating"], 100.0 * kinds["rating"] / graded))
    interest_rows = [r for r in all_rows if r["kind"] == "interest"]
    interest_breakdown = collections.Counter(int(r["val"]) for r in interest_rows)
    print("unseen interest   %d  (never %d, untriaged old grade %d)"
          % (kinds["interest"], kinds["never"], kinds["legacy"]))
    if interest_rows:
        print("  by level (training weight in parens): " + ", ".join(
            "%d\u00d7%d(%.2f)" % (interest_breakdown.get(i, 0), i, SC["interest_weights"].get(str(i), 0))
            for i in (1, 2, 3, 4, 5)))
    seen_rows = [r for r in all_rows if r["kind"] == "rating"]
    if seen_rows:
        sr_hits = sum(1 for r in seen_rows if r["val"] >= SC["hit_min"])
        print("  of those, hit rate on SEEN+RATED alone: %.0f%%  (%d/%d) -- the real truth "
              "signal; the combined figure above dilutes it with never/interest guesses"
              % (100.0 * sr_hits / len(seen_rows), sr_hits, len(seen_rows)))
    print()

    for k in (10, 20, 40):
        sub = [r for r in all_rows if r["rank"] and r["rank"] <= k]
        if sub:
            print("precision@%-3d      %.0f%%  (%d of %d graded in top %d)"
                  % (k, 100.0 * sum(1 for r in sub if r["val"] >= SC["hit_min"]) / len(sub),
                     sum(1 for r in sub if r["val"] >= SC["hit_min"]), len(sub), k))
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

    cfg = common.config(P.pool)
    old = cfg["weights"]
    lam = cfg.get("tune", {}).get("learning_rate", 0.6)
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
        if r["val"] <= SC["miss_max"]:
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
    print()
    crowd_agreement(all_rows, dirnames)

    if "--apply" in sys.argv:
        need = cfg.get("tune", {}).get("min_rows", 30)
        if len(rows) < need:
            print("\nnot applying: %d graded films with channel snapshots, need %d before "
                  "this pool gets its own weights" % (len(rows), need))
        else:
            common.set_pool_setting("weights", prop, P.pool, P.profile)
            print("\napplied new weights to pool %r in %s/profile.json"
                  % (P.pool, P.profile_dir))


if __name__ == "__main__":
    main()
