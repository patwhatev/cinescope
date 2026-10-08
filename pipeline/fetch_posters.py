"""Download poster thumbnails for the films currently in the UI build.

Posters live on a.ltrbxd.com, a plain image CDN with no Cloudflare
interstitial, so a direct request (no special headers needed) works. Saved
once to data/posters/<slug>.jpg; re-run is a no-op for anything already
on disk.
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

OUTDIR = os.path.join(common.DATA, "posters")


def main():
    with open(os.path.join(common.DATA, "scores.json"), encoding="utf-8") as fh:
        S = json.load(fh)
    films = common.load_films()
    top = int(os.environ.get("BUILD_TOP", "80"))
    slugs = [f["slug"] for f in S["films"][:top]]

    os.makedirs(OUTDIR, exist_ok=True)
    got = skip = miss = 0
    for slug in slugs:
        dest = os.path.join(OUTDIR, slug + ".jpg")
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            skip += 1
            continue
        url = (films.get(slug) or {}).get("poster")
        if not url:
            miss += 1
            continue
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
            with open(dest, "wb") as fh:
                fh.write(data)
            got += 1
            print("  + %s (%d KB)" % (slug, len(data) // 1024))
        except Exception as e:
            miss += 1
            print("  ! %s failed: %s" % (slug, e))
        time.sleep(0.25)
    print("posters: %d downloaded, %d already cached, %d missing" % (got, skip, miss))


if __name__ == "__main__":
    main()
