"""Turn a letterboxd /film/<slug>/ page into a structured record."""
import html as _html
import json
import re

_A = r'<a[^>]*href="/%s/([a-z0-9\-]+)/[^"]*"[^>]*>(.*?)</a>'


def _ld_json(page):
    """The page's schema.org Movie block: cleanest source for poster,
    synopsis, runtime and billed cast — falls back to {} if absent."""
    m = re.search(
        r'<script type="application/ld\+json">\s*/\* <!\[CDATA\[ \*/\s*(\{.*?\})\s*/\* \]\]> \*/\s*</script>',
        page, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except ValueError:
        return {}


def _runtime_minutes(iso):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", iso or "")
    if not m:
        return None
    h, mi = m.groups()
    return (int(h or 0) * 60) + int(mi or 0)


def _anchors(kind, chunk):
    """Ordered, de-duplicated (slug, display name) pairs for one link kind."""
    out, seen = [], set()
    for slug, label in re.findall(_A % kind, chunk, re.S):
        if slug in seen:
            continue
        seen.add(slug)
        name = _html.unescape(re.sub(r"<[^>]+>", "", label)).strip()
        out.append([slug, name])
    return out


def _section(page, heading):
    """The markup between an <h3> heading and the next <h3>."""
    m = re.search(r"<h3>(?:(?!</h3>).)*?%s.*?</h3>(.*?)(?=<h3>|</div>\s*</div>)"
                  % re.escape(heading), page, re.S)
    return m.group(1) if m else ""


def film(slug, page):
    title = ""
    m = re.search(r'<meta property="og:title" content="([^"]+)"', page)
    if m:
        title = _html.unescape(m.group(1))
    year = ""
    m = re.search(r'/films/year/(\d{4})/', page)
    if m:
        year = m.group(1)
    title = re.sub(r"\s*\(\d{4}\)\s*$", "", title).strip()

    # "Similar Films" edge list — scoped to its own section so sidebar
    # posters elsewhere on the page cannot leak in.
    similar = []
    m = re.search(r'<section class="section related-films.*?</section>', page, re.S)
    if m:
        seen = set()
        for s in re.findall(r'data-item-slug="([a-z0-9\-]+)"', m.group(0)):
            if s != slug and s not in seen:
                seen.add(s)
                similar.append(s)

    rating = rating_count = None
    m = re.search(r'"ratingValue":([0-9.]+)', page)
    if m:
        rating = float(m.group(1))
    m = re.search(r'"ratingCount":(\d+)', page)
    if m:
        rating_count = int(m.group(1))

    tmdb = imdb = ""
    m = re.search(r'themoviedb\.org/movie/(\d+)', page)
    if m:
        tmdb = m.group(1)
    m = re.search(r'imdb\.com/title/(tt\d+)', page)
    if m:
        imdb = m.group(1)

    ld = _ld_json(page)
    poster = (ld.get("image") or "").strip()
    synopsis = _html.unescape(ld.get("description") or "").strip()
    runtime = _runtime_minutes(ld.get("duration"))
    ld_cast = [_html.unescape(a.get("name", "")) for a in ld.get("actor") or [] if a.get("name")]

    # Credits block holds the directed-by line; the details pane holds the rest.
    return {
        "slug": slug,
        "title": title,
        "year": year,
        "directors": _anchors("director", page),
        "writers": _anchors("writer", page),
        "cast": _anchors("actor", page)[:18],
        "cast_billed": ld_cast[:10],   # json-ld order matches on-screen billing
        "genres": _anchors("films/genre", page),
        "themes": _anchors("films/theme", page),
        "mini_themes": _anchors("films/mini-theme", page),
        "rating": rating,
        "rating_count": rating_count,
        "tmdb": tmdb,
        "imdb": imdb,
        "similar": similar,
        "poster": poster,
        "synopsis": synopsis,
        "runtime": runtime,
    }
