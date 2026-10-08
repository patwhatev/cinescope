"""Append newly-kept films (seen and rated >= 4 in out/grades.csv, or an
untriaged old grade >= 4) to KEEPERS.md.

Idempotent: a slug already anywhere in KEEPERS.md is skipped, so re-running
after pull_grades.py only ever adds the delta. Run order each round:
  pull_grades.py  ->  tune.py  ->  update_keepers.py
"""
import csv
import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

PATH = os.path.join(common.ROOT, "KEEPERS.md")


def existing_slugs(text):
    # Film titles aren't a stable key (duplicate titles, re-releases); track
    # slugs in an HTML comment per row instead so re-runs can diff cleanly.
    return set(re.findall(r"<!--slug:([a-z0-9\-]+)-->", text))


def main():
    gpath = os.path.join(common.OUT, "grades.csv")
    if not os.path.exists(gpath):
        sys.exit("no grades.csv yet")
    with open(gpath, encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if common.seed_tier(r)]

    text = open(PATH, encoding="utf-8").read() if os.path.exists(PATH) else (
        "# Keepers\n\nThe running list of films confirmed via Dailies grading.\n")
    have = existing_slugs(text)
    new = [r for r in rows if r["slug"] not in have]
    if not new:
        print("nothing new — %d kept films already on the list" % len(have))
        return

    new.sort(key=lambda r: (-common.seed_tier(r), -float(r["score"] or 0)))
    iters = len(re.findall(r"^## Iteration", text, re.M))
    today = datetime.date.today().isoformat()
    lines = ["\n## Iteration %02d — %s, %d newly kept\n" % (iters + 1, today, len(new)),
              "| Film | Year | Weight | Score | |", "|---|---|---|---|---|"]
    for r in new:
        weight = "heavy (1.0)" if common.seed_tier(r) == 1.0 else "light (0.5)"
        lines.append("| %s | %s | %s | %s | <!--slug:%s--> |"
                      % (r["title"], r["year"], weight, r["score"], r["slug"]))

    with open(PATH, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("appended %d newly kept films to %s (iteration %02d)" % (len(new), PATH, iters + 1))


if __name__ == "__main__":
    main()
