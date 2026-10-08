"""Merge a grades dump pulled from the artifact's db into out/grades.csv.

Input: a JSON array of {slug, grade, seen} (fetched via Artifact action
"read_db", collection "grades" -- that call goes through the Artifact tool,
not this script, so paste its output to a file and point this at it).
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common


def main():
    dump_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/grades_dump.json"
    with open(dump_path, encoding="utf-8") as fh:
        dump = {r["slug"]: r for r in json.load(fh)}

    with open(os.path.join(common.DATA, "scores.json"), encoding="utf-8") as fh:
        S = json.load(fh)
    byslug = {f["slug"]: (i + 1, f) for i, f in enumerate(S["films"])}

    gpath = os.path.join(common.OUT, "grades.csv")
    existing = {}
    if os.path.exists(gpath):
        with open(gpath, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                existing[row["slug"]] = row

    cols = ["rank", "slug", "title", "year", "score", "g", "t", "p", "q",
            "grade", "seen", "note"]
    merged = dict(existing)
    for slug, r in dump.items():
        rank, f = byslug.get(slug, (0, None))
        c = f["channels"] if f else {"g": "", "t": "", "p": "", "q": ""}
        merged[slug] = {
            "rank": rank, "slug": slug,
            "title": f["title"] if f else slug, "year": f["year"] if f else "",
            "score": f["score"] if f else "",
            "g": c["g"], "t": c["t"], "p": c["p"], "q": c["q"],
            "grade": r.get("grade") or "", "seen": "y" if r.get("seen") else "",
            "note": existing.get(slug, {}).get("note", ""),
        }

    with open(gpath, "w", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        def rank_key(s):
            r = merged[s]["rank"]
            try:
                r = int(r)
            except (TypeError, ValueError):
                r = 0
            return (r == 0, r)
        for slug in sorted(merged, key=rank_key):
            wr.writerow(merged[slug])

    n_graded = sum(1 for r in merged.values() if r.get("grade"))
    print("merged %d graded rows from %s into %s (%d total rows)"
          % (len(dump), dump_path, gpath, len(merged)))
    print("%d rows now have a grade" % n_graded)


if __name__ == "__main__":
    main()
