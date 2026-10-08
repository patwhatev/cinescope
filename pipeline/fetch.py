"""Polite, disk-cached fetcher for letterboxd.com film pages.

Only /film/<slug>/ is used: it is the one endpoint that serves without a
Cloudflare interstitial, and it happens to carry everything we need
(crew, cast, genres, themes, mini-themes, tmdb/imdb ids, rating stats,
and a 12-film "Similar Films" edge list).
"""
import gzip
import os
import random
import time
import urllib.error
import urllib.request

CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "cache")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
MIN_INTERVAL = 1.1          # seconds between live requests
_last_hit = [0.0]


def _cache_path(slug):
    return os.path.join(CACHE, slug.replace("/", "_") + ".html.gz")


def _throttle():
    wait = MIN_INTERVAL - (time.time() - _last_hit[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0, 0.3))
    _last_hit[0] = time.time()


def film_page(slug, max_age_days=30, retries=3):
    """Return HTML for /film/<slug>/, or None if the film does not exist.

    A 404 is cached as an empty file so a bad slug is only ever requested once.
    """
    os.makedirs(CACHE, exist_ok=True)
    path = _cache_path(slug)
    if os.path.exists(path):
        if time.time() - os.path.getmtime(path) < max_age_days * 86400:
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
                return fh.read() or None

    url = "https://letterboxd.com/film/%s/" % slug
    for attempt in range(retries):
        _throttle()
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                html = raw.decode("utf-8", errors="replace")
            break
        except urllib.error.HTTPError as err:
            if err.code == 404:
                html = ""
                break
            if err.code in (403, 429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(4 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(4 * (attempt + 1))
                continue
            raise
    else:
        return None

    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(html)
    return html or None


def person_page(kind, slug, max_age_days=30):
    """Filmography page for /director/<slug>/, /actor/<slug>/, /writer/<slug>/."""
    import gzip as _gz
    import os as _os
    import time as _t
    import urllib.error as _ue
    import urllib.request as _ur
    _os.makedirs(CACHE, exist_ok=True)
    path = _os.path.join(CACHE, "%s__%s.html.gz" % (kind, slug))
    if _os.path.exists(path) and _t.time() - _os.path.getmtime(path) < max_age_days * 86400:
        with _gz.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            return fh.read() or None
    url = "https://letterboxd.com/%s/%s/" % (kind, slug)
    for attempt in range(3):
        _throttle()
        req = _ur.Request(url, headers={"User-Agent": UA, "Accept": "text/html",
                                        "Accept-Encoding": "gzip"})
        try:
            with _ur.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = _gz.decompress(raw)
                page = raw.decode("utf-8", errors="replace")
            break
        except _ue.HTTPError as err:
            if err.code == 404:
                page = ""
                break
            if attempt < 2:
                _t.sleep(4 * (attempt + 1))
                continue
            raise
        except Exception:
            if attempt < 2:
                _t.sleep(4 * (attempt + 1))
                continue
            raise
    else:
        return None
    with _gz.open(path, "wt", encoding="utf-8") as fh:
        fh.write(page)
    return page or None
