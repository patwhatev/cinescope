"""Theme-vector helpers shared by score.py and pools.py.

A film's theme vector is its letterboxd mini-themes, themes and genres,
idf-weighted over the whole crawled corpus and unit-normalised, so cosine
between two vectors is "how alike are these films' flavour", with rare
descriptors counting for more than "Drama".
"""
import collections
import math


def tokens(rec, tw):
    out = {}
    for key, w in (("mini_themes", tw["mini_theme"]), ("themes", tw["theme"]),
                   ("genres", tw["genre"])):
        for slug, _ in rec.get(key) or []:
            k = "%s:%s" % (key, slug)
            out[k] = max(out.get(k, 0), w)
    return out


def unit(vec):
    n = math.sqrt(sum(v * v for v in vec.values()))
    return {k: v / n for k, v in vec.items()} if n else {}


def dot(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0) for k, v in a.items())


class ThemeSpace:
    def __init__(self, films, tw):
        self.tw = tw
        corpus = [r for r in films.values() if not r.get("dead")]
        df = collections.Counter()
        for r in corpus:
            for t in tokens(r, tw):
                df[t] += 1
        n = max(1, len(corpus))
        self.idf = {t: math.log(1 + n / (1 + d)) for t, d in df.items()}
        self._cache = {}

    def vec(self, rec):
        slug = rec.get("slug")
        if slug in self._cache:
            return self._cache[slug]
        v = unit({t: w * self.idf.get(t, 1.0) for t, w in tokens(rec, self.tw).items()})
        if slug:
            self._cache[slug] = v
        return v

    def centroid(self, weighted_recs):
        c = collections.defaultdict(float)
        for rec, w in weighted_recs:
            for t, val in self.vec(rec).items():
                c[t] += w * val
        return unit(c)


def pretty(token):
    return token.split(":", 1)[1].replace("-", " ") if ":" in token else token
