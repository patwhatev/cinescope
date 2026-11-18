"""Write this pool's grades.csv (verdicts + channel snapshots for tune.py),
and the profile's watchlist.csv.

  python3 pipeline/pull_grades.py              -- read the profile's grades.db
  python3 pipeline/pull_grades.py dump.json    -- first merge a JSON array of grade
    docs into grades.db (MODE=artifact: the "grades" collection via ArtifactData)
  python3 pipeline/pull_grades.py dump_dir/    -- same, from a directory of <slug>.json

Each doc carries {slug, grade, status, rating, interest, never, pool}:
`status` is "seen" / "unseen" / null, `pool` is the reel it was graded in
(see common.verdict for how the rest combine, pools.assign for `pool`).
"""
import csv
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import pools

P = common.paths()


def load_dump(path):
    if os.path.isdir(path):
        docs = []
        for p in sorted(glob.glob(os.path.join(path, "*.json"))):
            with open(p, encoding="utf-8") as fh:
                docs.append(json.load(fh))
        return docs
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def merge_dump(docs):
    conn = common.grades_db(P.profile)
    for r in docs:
        if not r.get("slug"):
            continue
        conn.execute(
            "INSERT OR REPLACE INTO grades(%s) VALUES (%s)"
            % (", ".join(common.GRADE_DB_COLUMNS), ", ".join("?" * len(common.GRADE_DB_COLUMNS))),
            [r.get("slug"), r.get("title"), r.get("grade"), r.get("status"), r.get("rating"),
             r.get("interest"), 1 if r.get("never") else 0, r.get("pool"), r.get("ts")])
    conn.commit()
    conn.close()


def cell(v):
    return "" if v is None or v is False else v


def main():
    dump_path = sys.argv[1] if len(sys.argv) > 1 else None
    if dump_path:
        merge_dump(load_dump(dump_path))
    rows = common.read_db_grades(P.profile)
    if not rows:
        print("no grades yet in %s" % P.grades_db)
    recs = common.load_films()
    assignment = pools.assign(P.profile, rows, recs)
    sc = common.scale(common.config(P.pool))

    S = common.load_json(P.scores, {"films": []})
    byslug = {f["slug"]: (i + 1, f) for i, f in enumerate(S["films"])}

    existing = common.read_grades(P.grades_csv)
    merged = {}
    for slug, r in rows.items():
        if assignment.get(slug) != P.pool:
            continue
        rank, f = byslug.get(slug, (0, None))
        rec = recs.get(slug, {})
        old_row = existing.get(slug, {})
        # A promoted seed drops out of scores.json entirely (seeds aren't
        # scored against themselves) -- keep its last channel snapshot, or
        # tune.py loses the hit-rate signal for exactly the best-rated films.
        if f:
            row_rank, row_score, c = rank, f["score"], f["channels"]
        else:
            row_rank = old_row.get("rank") or rank
            row_score = old_row.get("score") or ""
            c = {k: old_row.get(k, "") for k in ("g", "t", "p", "q")}
        status = r.get("status")
        merged[slug] = {
            "rank": row_rank, "slug": slug,
            "title": (f or rec).get("title") or r.get("title") or slug,
            "year": (f or rec).get("year") or old_row.get("year") or "",
            "score": row_score,
            "g": c["g"], "t": c["t"], "p": c["p"], "q": c["q"],
            "grade": cell(r.get("grade")),
            "seen": {"seen": "y", "unseen": "n"}.get(status, ""),
            "rating": cell(r.get("rating")), "interest": cell(r.get("interest")),
            "never": "y" if r.get("never") else "",
            "pool": P.pool,
            "note": old_row.get("note", ""),
        }
    # Ungraded rows report.py wrote (the current top slice) stay, so the
    # sheet still lines up with the reel.
    for slug, old in existing.items():
        if slug not in merged and slug not in rows:
            merged[slug] = old

    def rank_key(s):
        try:
            r = int(merged[s]["rank"])
        except (TypeError, ValueError):
            r = 0
        return (r == 0, r)

    os.makedirs(P.pool_dir, exist_ok=True)
    with open(P.grades_csv, "w", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=common.GRADE_COLS, extrasaction="ignore")
        wr.writeheader()
        for slug in sorted(merged, key=rank_key):
            wr.writerow(merged[slug])

    kinds = {}
    for r in merged.values():
        v = common.verdict(r, sc)
        if v:
            kinds[v[0]] = kinds.get(v[0], 0) + 1
    print("[%s/%s] %d of %d profile grades belong to this pool -> %s"
          % (P.profile, P.pool, sum(1 for s in rows if assignment.get(s) == P.pool),
             len(rows), P.grades_csv))
    print("  seen+rated %d · unseen interest %d · never %d · untriaged old grade %d"
          % tuple(kinds.get(k, 0) for k in ("rating", "interest", "never", "legacy")))

    # Watchlist: profile-wide, unseen at hit_min+, most wanted first.
    watch = []
    for slug, r in rows.items():
        v = common.verdict(r, sc)
        if v and v[0] == "interest" and v[1] >= sc["hit_min"]:
            rec = recs.get(slug, {})
            watch.append((v[1], slug, rec.get("title") or r.get("title") or slug,
                          rec.get("year") or "", assignment.get(slug) or ""))
    watch.sort(key=lambda x: (-x[0], x[2]))
    with open(P.watchlist, "w", encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["interest", "title", "year", "pool", "slug", "letterboxd"])
        for interest, slug, title, year, pool in watch:
            wr.writerow([int(interest), title, year, pool, slug,
                         "https://letterboxd.com/film/%s/" % slug])
    print("wrote %s (%d films)" % (P.watchlist, len(watch)))


if __name__ == "__main__":
    main()
