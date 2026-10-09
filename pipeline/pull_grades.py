"""Merge graded rows into out/grades.csv, and write out/watchlist.csv.

  python3 pipeline/pull_grades.py              -- read data/grades.db (self-hosted MODE=local)
  python3 pipeline/pull_grades.py dump.json    -- read a JSON array (MODE=artifact: the
    "grades" collection via the ArtifactData tool)
  python3 pipeline/pull_grades.py dump_dir/    -- read a directory of <slug>.json docs
    (same tool, with out_dir set)

Each doc carries {slug, grade, status, rating, interest, never}: `status` is
"seen" / "unseen" / null, and `grade` is the pre-split star (see
common.verdict for how they combine).
"""
import csv
import glob
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common


def load_dump(path):
    if os.path.isdir(path):
        docs = []
        for p in sorted(glob.glob(os.path.join(path, "*.json"))):
            with open(p, encoding="utf-8") as fh:
                docs.append(json.load(fh))
        return docs
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_local_db():
    path = os.path.join(common.DATA, "grades.db")
    if not os.path.exists(path):
        sys.exit("no data/grades.db yet -- grade something in the local server first, "
                  "or pass an artifact dump path")
    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(grades)")]
    rows = conn.execute("SELECT %s FROM grades" % ", ".join(cols)).fetchall()
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


def cell(v):
    return "" if v is None or v is False else v


def main():
    dump_path = sys.argv[1] if len(sys.argv) > 1 else None
    docs = load_dump(dump_path) if dump_path else load_local_db()
    dump = {r["slug"]: r for r in docs}
    source = dump_path or os.path.join(common.DATA, "grades.db")

    with open(os.path.join(common.DATA, "scores.json"), encoding="utf-8") as fh:
        S = json.load(fh)
    byslug = {f["slug"]: (i + 1, f) for i, f in enumerate(S["films"])}
    recs = common.load_films()

    existing = common.read_grades()
    merged = dict(existing)
    for slug, r in dump.items():
        rank, f = byslug.get(slug, (0, None))
        rec = recs.get(slug, {})
        old_row = existing.get(slug, {})
        # A promoted seed drops out of scores.json entirely (seeds aren't
        # scored against themselves) -- without this fallback, every run
        # after a film graduates to seeds.txt silently blanks the channel
        # snapshot that tune.py needs to grade it, which was quietly
        # erasing the hit-rate signal for your best-rated films.
        if f:
            row_rank, row_score, c = rank, f["score"], f["channels"]
        else:
            row_rank = old_row.get("rank") or rank
            row_score = old_row.get("score") or ""
            c = {k: old_row.get(k, "") for k in ("g", "t", "p", "q")}
        status = r.get("status")
        merged[slug] = {
            "rank": row_rank, "slug": slug,
            "title": (f or rec).get("title") or old_row.get("title") or slug,
            "year": (f or rec).get("year") or old_row.get("year") or "",
            "score": row_score,
            "g": c["g"], "t": c["t"], "p": c["p"], "q": c["q"],
            "grade": cell(r.get("grade")),
            "seen": {"seen": "y", "unseen": "n"}.get(status, ""),
            "rating": cell(r.get("rating")), "interest": cell(r.get("interest")),
            "never": "y" if r.get("never") else "",
            "note": old_row.get("note", ""),
        }

    def rank_key(s):
        try:
            r = int(merged[s]["rank"])
        except (TypeError, ValueError):
            r = 0
        return (r == 0, r)

    gpath = os.path.join(common.OUT, "grades.csv")
    with open(gpath, "w", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=common.GRADE_COLS, extrasaction="ignore")
        wr.writeheader()
        for slug in sorted(merged, key=rank_key):
            wr.writerow(merged[slug])

    kinds = {}
    for r in merged.values():
        v = common.verdict(r)
        if v:
            kinds[v[0]] = kinds.get(v[0], 0) + 1
    print("merged %d rows from %s into %s (%d total rows)"
          % (len(dump), source, gpath, len(merged)))
    print("  seen+rated %d · unseen interest %d · never %d · untriaged old grade %d"
          % tuple(kinds.get(k, 0) for k in ("rating", "interest", "never", "legacy")))

    # Watchlist: unseen, interest >= 3, most wanted first.
    watch = []
    for r in merged.values():
        v = common.verdict(r)
        if v and v[0] == "interest" and v[1] >= 3:
            watch.append((v[1], float(r["score"] or 0), r))
    watch.sort(key=lambda x: (-x[0], -x[1]))
    wpath = os.path.join(common.OUT, "watchlist.csv")
    with open(wpath, "w", encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["interest", "title", "year", "score", "slug", "letterboxd"])
        for interest, _, r in watch:
            wr.writerow([int(interest), r["title"], r["year"], r["score"], r["slug"],
                         "https://letterboxd.com/film/%s/" % r["slug"]])
    print("wrote %s (%d films)" % (wpath, len(watch)))


if __name__ == "__main__":
    main()
