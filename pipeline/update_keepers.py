"""Append newly-kept films (seen and rated into a seed tier, in any pool) to
the profile's KEEPERS.md.

Idempotent: a slug already anywhere in KEEPERS.md is skipped, so re-running
after pull_grades.py only ever adds the delta. Run order each round:
  pull_grades.py  ->  tune.py  ->  update_keepers.py
"""
import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import pools

P = common.paths()
PATH = P.keepers


def existing_slugs(text):
    # Film titles aren't a stable key (duplicate titles, re-releases); track
    # slugs in an HTML comment per row instead so re-runs can diff cleanly.
    return set(re.findall(r"<!--slug:([a-z0-9\-]+)-->", text))


def main():
    sc = common.scale(common.config())
    db = common.read_db_grades(P.profile)
    films = common.load_films()
    assignment = pools.assign(P.profile, db, films)
    rows = []
    for slug, r in db.items():
        tier = common.seed_tier(r, sc)
        if tier:
            rec = films.get(slug) or {}
            rows.append({"slug": slug, "tier": tier, "pool": assignment.get(slug) or "",
                         "title": rec.get("title") or r.get("title") or slug,
                         "year": rec.get("year") or ""})

    text = open(PATH, encoding="utf-8").read() if os.path.exists(PATH) else (
        "# Keepers\n\nThe running list of films confirmed via Dailies grading.\n")
    have = existing_slugs(text)
    new = [r for r in rows if r["slug"] not in have]
    if not new:
        print("nothing new — %d kept films already on the list" % len(have))
        return

    new.sort(key=lambda r: (r["pool"], -r["tier"], r["title"]))
    iters = len(re.findall(r"^## Iteration", text, re.M))
    today = datetime.date.today().isoformat()
    lines = ["\n## Iteration %02d — %s, %d newly kept\n" % (iters + 1, today, len(new)),
              "| Film | Year | Pool | Weight | |", "|---|---|---|---|---|"]
    for r in new:
        weight = "%s (%.1f)" % ("heavy" if r["tier"] >= 1.0 else "light", r["tier"])
        lines.append("| %s | %s | %s | %s | <!--slug:%s--> |"
                      % (r["title"], r["year"], r["pool"], weight, r["slug"]))

    fresh = not os.path.exists(PATH)
    with open(PATH, "a", encoding="utf-8") as fh:
        if fresh:
            fh.write(text.rstrip("\n") + "\n")
        fh.write("\n".join(lines) + "\n")
    print("appended %d newly kept films to %s (iteration %02d)" % (len(new), PATH, iters + 1))


if __name__ == "__main__":
    main()
