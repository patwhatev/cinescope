"""Fold starred keepers belonging to this pool into its seeds.txt.

Seen ratings in the profile scale's seed_tiers promote (by default 5 stars
-> 1.0 heavy, 4 stars -> 0.5 light); anything else doesn't.

Only films you've seen promote (or an old pre-split grade not yet triaged):
a want-to-see score is a guess about taste, so it never becomes a seed.

Everything above the "# --- promoted from grading ---" marker in seeds.txt is
yours — hand-authored seeds are never touched. Everything below it is fully
regenerated from grades.csv on every run, so lowering a star later removes
that seed next time this runs, and raising one updates its weight.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import pools

MARKER = common.SEED_MARKER
P = common.paths()
PATH = P.seeds


def main():
    rows = common.read_db_grades(P.profile)
    films = common.load_films()
    sc = common.scale(common.config(P.pool))
    # pools.assign only treats *hand-written* seeds as fixed homes, so a
    # film promoted here last round can still move if a better pool appears.
    assignment = pools.assign(P.profile, rows, films)

    promoted = []
    for slug, r in rows.items():
        if assignment.get(slug) != P.pool:
            continue
        tier = sc["seed_tiers"] and common.seed_tier(r, sc)
        if tier:
            title = (films.get(slug) or {}).get("title") or r.get("title") or slug
            promoted.append((slug, tier, title, "heavy" if tier >= 1.0 else "light"))

    text = open(PATH, encoding="utf-8").read() if os.path.exists(PATH) else ""
    head = text.split(MARKER)[0].rstrip("\n")
    hand_slugs = {ln.split("|")[0].strip() for ln in head.splitlines()
                  if ln.strip() and not ln.strip().startswith("#")}

    lines = [head, "", MARKER]
    skipped = 0
    for slug, weight, title, tier in sorted(promoted, key=lambda x: -x[1]):
        if slug in hand_slugs:
            skipped += 1   # a hand-authored seed also got graded highly — leave it alone
            continue
        lines.append("%-34s | %.1f | %s grading: %s" % (slug, weight, tier, title))

    with open(PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    heavy = sum(1 for _, w, _, _ in promoted if w >= 1.0)
    light = len(promoted) - heavy
    print("[%s/%s] seeds.txt: %d hand-authored seeds kept untouched"
          % (P.profile, P.pool, len(hand_slugs)))
    print("promoted %d heavy + %d light from grading%s"
          % (heavy, light, " (%d already hand-seeded, skipped)" % skipped if skipped else ""))


if __name__ == "__main__":
    main()
