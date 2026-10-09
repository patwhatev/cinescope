import collections
import csv
import json
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "out")

JUNK = re.compile(
    r"making of|behind the scenes|director'?s journey|a look at|featurette|"
    r"interview|outtakes|deleted scenes|anniversary|commentary|trailer|"
    r"\bdocumentary about\b", re.I)


def config():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as fh:
        return json.load(fh)


def seeds():
    out = []
    with open(os.path.join(ROOT, "seeds.txt"), encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            out.append((parts[0], float(parts[1]) if len(parts) > 1 else 1.0))
    return out


def load_films():
    path = os.path.join(DATA, "films.jsonl")
    films = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    films[rec["slug"]] = rec
    return films


def save_films(films):
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, "films.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for slug in sorted(films):
            fh.write(json.dumps(films[slug], ensure_ascii=False) + "\n")


def is_junk(rec, min_count):
    """Featurettes, making-ofs and near-unrated entries pollute filmographies."""
    if JUNK.search(rec.get("title") or ""):
        return True
    if (rec.get("rating_count") or 0) < min_count:
        return True
    return False


def label(rec):
    return "%s (%s)" % (rec.get("title") or rec["slug"], rec.get("year") or "?")


def select_for_reel(films_sorted, top):
    """Fresh (ungraded) candidates lead, capped per director so a handful of
    well-connected favorites (Lynch, Miike...) can't fill the reel on their
    own; already-graded films trail so a revisit is still possible but never
    crowds out new material. Shared by build_ui.py and fetch_posters.py so
    their film lists can't drift apart.
    """
    cap = config().get("reel_director_cap")
    fresh, reviewed, seen_dir = [], [], collections.Counter()
    overflow = []  # capped-out fresh films -- still shown, just after the diverse front
    for f in films_sorted:
        if f["already_graded"]:
            reviewed.append(f)
            continue
        dirs = f.get("directors") or []
        if cap and dirs and max(seen_dir[d] for d in dirs) >= cap:
            overflow.append(f)
            continue
        for d in dirs:
            seen_dir[d] += 1
        fresh.append(f)
    return (fresh + overflow + reviewed)[:top]


# ---- verdicts ---------------------------------------------------------------
# A grade is one of two different questions, depending on whether you've seen
# the film: "how much did you enjoy it" (rating) or "how much do you want to
# see it" (interest, or a hard `never`). `grade` is the pre-split 1-5 star,
# kept as-is so an untriaged row still means what it meant before.

GRADE_COLS = ["rank", "slug", "title", "year", "score", "g", "t", "p", "q",
              "grade", "seen", "rating", "interest", "never", "note"]

INTEREST_WEIGHT = 0.5   # want-to-see is a guess about taste, not a verdict on it


def _num(v):
    try:
        return float(str(v).strip()) if v not in (None, "") else None
    except ValueError:
        return None


def _flag(v):
    return (v or "").strip().lower() in ("y", "yes", "1", "true")


def verdict(row):
    """One grades.csv row -> (kind, value 1-5, weight), or None if ungraded.

      seen + rating      -> ("rating",   rating,   1.0)  enjoyment; can seed
      unseen + never     -> ("never",    1,        1.0)  a hard no
      unseen + interest  -> ("interest", interest, 0.5)  watchlist; never seeds
      only an old grade  -> ("legacy",   grade,    1.0)  pre-split, ambiguous
    """
    seen = (row.get("seen") or "").strip().lower()
    rating, interest = _num(row.get("rating")), _num(row.get("interest"))
    if seen.startswith("y") and rating:
        return ("rating", rating, 1.0)
    if seen.startswith("n") and _flag(row.get("never")):
        return ("never", 1.0, 1.0)
    if seen.startswith("n") and interest:
        return ("interest", interest, INTEREST_WEIGHT)
    grade = _num(row.get("grade"))
    if grade:
        return ("legacy", grade, 1.0)
    return None


def seed_tier(row):
    """1.0 / 0.5 seed weight for a film you've enjoyed, else None. Only seen
    ratings (or an untriaged old grade) promote — interest never does."""
    v = verdict(row)
    if not v or v[0] not in ("rating", "legacy"):
        return None
    return 1.0 if v[1] >= 5 else 0.5 if v[1] >= 4 else None


def read_grades():
    path = os.path.join(OUT, "grades.csv")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return {r["slug"]: r for r in csv.DictReader(fh)}


def triage_slugs(reel_slugs):
    """Graded slugs the reel doesn't carry (promoted seeds, films that fell out
    of the top slice), so they can still be re-triaged. Reads grades.csv, plus
    a raw db dump at $GRADES_DUMP for grades not yet pulled."""
    slugs = set(read_grades())
    dump = os.environ.get("GRADES_DUMP")
    if dump:
        if os.path.isdir(dump):
            slugs |= {n[:-5] for n in os.listdir(dump) if n.endswith(".json")}
        else:
            with open(dump, encoding="utf-8") as fh:
                slugs |= {r["slug"] for r in json.load(fh)}
    return sorted(slugs - set(reel_slugs))


def next_iteration():
    """Smallest unused "NN" for out/iteration-NN.md, zero-padded, starting
    at 01. Used by the UI's re-weigh button so it doesn't need a human to
    pick a label each round."""
    best = 0
    if os.path.isdir(OUT):
        for name in os.listdir(OUT):
            m = re.match(r"iteration-(\d+)\.md$", name)
            if m:
                best = max(best, int(m.group(1)))
    return "%02d" % (best + 1)
