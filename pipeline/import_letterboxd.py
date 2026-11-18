"""Import a letterboxd profile's watched films, ratings and watchlist into a
cinescope profile's grades.db, so they steer scoring the same way in-app
grading does.

  python3 pipeline/import_letterboxd.py <letterboxd-user> [--profile NAME]
  python3 pipeline/import_letterboxd.py <letterboxd-user> --dry-run   # show what would change

Only /<user>/films/ and /<user>/watchlist/ are used -- both serve without a
Cloudflare interstitial (/films/ratings/ and /films/diary/ don't).

Letterboxd half-stars are mapped onto the profile's own scale (see
common.SCALES "letterboxd"): with "standard" they map straight across, with
"top-heavy" (3 = a hit, 4-5 rare) they're shifted down. A liked-but-unrated
film counts as the scale's lowest seed tier; a watched-but-unrated film is
recorded as seen with no rating (excluded from recommendations, no weight
either way); the watchlist becomes unseen at the scale's watchlist_interest.

Imported rows carry no pool -- pools.assign puts each in its nearest pool.
In-app grades win: a row you've already rated or triaged is left alone (and
reported if letterboxd disagrees), except that a film you've since watched
moves from unseen to seen with its letterboxd rating.
"""
import argparse
import html
import os
import re
import sqlite3
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import fetch

def lb_to_rating(half_stars, liked, sc):
    if not half_stars:
        if not liked:
            return None
        tiers = [int(k) for k in sc["seed_tiers"]] or [sc["hit_min"]]
        return min(tiers)
    for floor, rating in sc["letterboxd"]:
        if half_stars >= floor:
            return rating
    return 1


def get(url):
    fetch._throttle()
    req = urllib.request.Request(url, headers={
        "User-Agent": fetch.UA, "Accept": "text/html",
        "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def grid(user, section):
    """Every poster on /<user>/<section>/, across pages:
    [{slug, title, half_stars, liked}]."""
    out, page = [], 1
    while True:
        url = "https://letterboxd.com/%s/%s/%s" % (
            user, section, "" if page == 1 else "page/%d/" % page)
        body = get(url)
        items = body.split('<li class="griditem">')[1:]
        if not items:
            break
        for it in items:
            m = re.search(r'data-item-slug="([^"]+)"', it)
            if not m:
                continue
            name = re.search(r'data-item-name="([^"]*)"', it)
            title = html.unescape(name.group(1)) if name else m.group(1)
            title = re.sub(r"\s*\(\d{4}\)$", "", title)
            r = re.search(r"rated-(\d+)", it)
            out.append({"slug": m.group(1), "title": title,
                        "half_stars": int(r.group(1)) if r else None,
                        "liked": "icon-liked" in it})
        print("  %s page %d: %d" % (section, page, len(items)), flush=True)
        if "/%s/%s/page/%d/" % (user, section, page + 1) not in body:
            break
        page += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("user", help="letterboxd username")
    ap.add_argument("--profile", help="cinescope profile to import into")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.profile:
        os.environ["CINESCOPE_PROFILE"] = args.profile
    profile = common.profile_name()
    sc = common.scale(common.config(profile=profile))
    WATCHLIST_INTEREST = sc["watchlist_interest"]

    watched = grid(args.user, "films")
    watchlist = grid(args.user, "watchlist")

    conn = common.grades_db(profile)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(grades)")]
    rows = {r[0]: dict(zip(cols, r))
            for r in conn.execute("SELECT %s FROM grades" % ", ".join(cols))}
    now = int(time.time() * 1000)
    writes, kept, conflicts = {}, [], []

    for f in watched:
        rating = lb_to_rating(f["half_stars"], f["liked"], sc)
        old = rows.get(f["slug"])
        new = {"slug": f["slug"], "title": f["title"], "status": "seen",
               "rating": rating, "interest": None, "never": 0, "ts": now}
        if old and old.get("status") == "seen" and (old.get("rating") or not rating):
            if rating and old.get("rating") != rating:
                conflicts.append("%s: app %s, letterboxd -> %s (kept app)"
                                 % (f["slug"], old["rating"], rating))
            kept.append(f["slug"])
            continue
        if old and old.get("never"):
            conflicts.append("%s: never in app, but watched on letterboxd (%s) -> now seen"
                             % (f["slug"], rating or "unrated"))
        writes[f["slug"]] = new

    for f in watchlist:
        old = rows.get(f["slug"])
        if f["slug"] in writes:
            continue
        if old and (old.get("status") or old.get("never") or old.get("grade")):
            if old.get("never") or (old.get("interest") or 0) < WATCHLIST_INTEREST \
                    and old.get("status") == "unseen":
                conflicts.append("%s: on letterboxd watchlist, app says %s (kept app)"
                                 % (f["slug"], "never" if old.get("never")
                                    else "interest %s" % old.get("interest")))
            kept.append(f["slug"])
            continue
        writes[f["slug"]] = {"slug": f["slug"], "title": f["title"], "status": "unseen",
                             "rating": None, "interest": WATCHLIST_INTEREST,
                             "never": 0, "ts": now}

    rated = [f for f in watched if f["half_stars"] or f["liked"]]
    print("letterboxd/%s: %d watched (%d rated or liked), %d on watchlist"
          % (args.user, len(watched), len(rated), len(watchlist)))
    print("  %d rows to write, %d already graded in app" % (len(writes), len(kept)))
    for c in conflicts:
        print("  ! " + c)
    if args.dry_run:
        for w in writes.values():
            print("  %-44s %-6s rating=%s interest=%s"
                  % (w["slug"], w["status"], w["rating"], w["interest"]))
        return
    for w in writes.values():
        old = rows.get(w["slug"]) or {}
        conn.execute(
            "INSERT OR REPLACE INTO grades(slug, title, grade, status, rating, interest, never, pool, ts)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (w["slug"], w["title"], old.get("grade"), w["status"], w["rating"],
             w["interest"], w["never"], old.get("pool"), w["ts"]))
    conn.commit()
    print("wrote %d rows to profile %s -- see where they landed with: "
          "python3 pipeline/profiles.py assign" % (len(writes), profile))


if __name__ == "__main__":
    main()
