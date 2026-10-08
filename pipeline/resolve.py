"""Resolve human film titles to letterboxd slugs, disambiguating by year."""
import re
import sys

import fetch
import parse


def candidates(title, year):
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    base = re.sub(r"^(the|a|an)-", "", base)
    opts = [base, "%s-%s" % (base, year)]
    stripped = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if stripped != base:
        opts += [stripped, "%s-%s" % (stripped, year)]
    opts += ["%s-1" % base, "%s-2" % base]
    seen, out = set(), []
    for o in opts:
        if o not in seen:
            seen.add(o)
            out.append(o)
    return out


def resolve(title, year):
    best = None
    for slug in candidates(title, year):
        page = fetch.film_page(slug)
        if not page:
            continue
        rec = parse.film(slug, page)
        if rec["year"] == str(year):
            return slug, rec
        if best is None:
            best = (slug, rec)
    return best if best else (None, None)


if __name__ == "__main__":
    for line in open(sys.argv[1], encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        title, year = [p.strip() for p in line.rsplit("|", 1)]
        slug, rec = resolve(title, year)
        if slug and rec["year"] == str(year):
            print("OK    %-42s %s (%s)  r=%s n=%s"
                  % (slug, rec["title"], rec["year"], rec["rating"], rec["rating_count"]))
        elif slug:
            print("YEAR? %-42s got %s (%s) wanted %s" % (slug, rec["title"], rec["year"], year))
        else:
            print("MISS  %-42s %s | %s" % ("-", title, year))
