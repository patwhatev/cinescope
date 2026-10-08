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
