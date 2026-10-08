"""Re-run parse.py over every cached film page, no network calls.

Use this after changing parse.py's extraction logic — the 30-day disk cache
means a plain re-run of crawl.py would serve the same cached HTML anyway, so
this just re-derives films.jsonl from what is already on disk.
"""
import gzip
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import parse


def main():
    films = common.load_films()
    updated = 0
    for slug in list(films):
        path = os.path.join(common.DATA, "cache", slug.replace("/", "_") + ".html.gz")
        if not os.path.exists(path):
            continue
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            page = fh.read()
        if not page:
            continue
        films[slug] = parse.film(slug, page)
        updated += 1
    common.save_films(films)
    print("reparsed %d / %d films from cache" % (updated, len(films)))


if __name__ == "__main__":
    main()
