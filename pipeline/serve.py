"""Self-hosted server for Dailies: localhost only, stdlib-only, no deps.

Serves the static page + poster images, and a tiny JSON API backing the
grading state that pipeline/build_ui.py's MODE=local variant writes to.

    python3 pipeline/serve.py            # http://localhost:8420
    python3 pipeline/serve.py --port 9000

Grades land in data/grades.db (sqlite3, stdlib). Each row is the full
seen/unseen verdict doc the frontend sends: {slug, title, grade, status,
rating, interest, never, ts} -- see common.verdict for how these combine.
`grade` is kept only as the pre-split legacy star for rows from before this
schema existed.
"""
import argparse
import json
import mimetypes
import os
import sqlite3
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

DB_PATH = os.path.join(common.DATA, "grades.db")
STATIC_ROOTS = {
    "": os.path.join(common.OUT, "dailies.html"),      # GET /
    "posters": os.path.join(common.DATA, "posters"),    # GET /posters/<slug>.jpg
}
COLUMNS = ["slug", "title", "grade", "status", "rating", "interest", "never", "ts"]


def db():
    os.makedirs(common.DATA, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS grades(
        slug TEXT PRIMARY KEY, title TEXT, grade INTEGER, status TEXT,
        rating INTEGER, interest INTEGER, never INTEGER, ts INTEGER
    )""")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(grades)")}
    if "status" not in cols:
        # Migrating a database from the pre-redesign schema (slug, title,
        # grade, seen, ts) -- add the new columns, keep the old `grade` as
        # the legacy star, drop `seen` (status carries that distinction now).
        for col, sqltype in (("status", "TEXT"), ("rating", "INTEGER"),
                             ("interest", "INTEGER"), ("never", "INTEGER")):
            conn.execute("ALTER TABLE grades ADD COLUMN %s %s" % (col, sqltype))
        conn.commit()
    return conn


class Handler(BaseHTTPRequestHandler):
    server_version = "DailiesLocal/2"

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, content_type=None):
        if not os.path.isfile(path):
            self.send_error(404, "not found")
            return
        ctype = content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
        data = open(path, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache" if ctype == "text/html" else "max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        parts = [p for p in parsed.path.split("/") if p]

        if not parts:
            return self._file(STATIC_ROOTS[""], "text/html; charset=utf-8")

        if parts[0] == "posters" and len(parts) == 2:
            safe = os.path.basename(parts[1])  # no path traversal
            return self._file(os.path.join(STATIC_ROOTS["posters"], safe), "image/jpeg")

        if parts == ["api", "grades"]:
            conn = db()
            rows = conn.execute(
                "SELECT %s FROM grades" % ", ".join(COLUMNS)).fetchall()
            conn.close()
            return self._json(200, [
                {"slug": s, "title": t, "grade": g, "status": st,
                 "rating": ra, "interest": it, "never": bool(nv), "ts": ts}
                for s, t, g, st, ra, it, nv, ts in rows
            ])

        self.send_error(404, "not found")

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "grades":
            slug = parts[2]
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json(400, {"error": "bad json"})
            row = {
                "slug": slug, "title": body.get("title") or slug,
                "grade": body.get("grade"), "status": body.get("status"),
                "rating": body.get("rating"), "interest": body.get("interest"),
                "never": 1 if body.get("never") else 0,
                "ts": int(time.time() * 1000),
            }
            conn = db()
            conn.execute(
                """INSERT INTO grades(%s) VALUES (%s)
                   ON CONFLICT(slug) DO UPDATE SET
                     title=excluded.title, grade=excluded.grade, status=excluded.status,
                     rating=excluded.rating, interest=excluded.interest,
                     never=excluded.never, ts=excluded.ts"""
                % (", ".join(COLUMNS), ", ".join("?" * len(COLUMNS))),
                [row[c] for c in COLUMNS],
            )
            conn.commit()
            conn.close()
            return self._json(200, {"ok": True, **{c: row[c] for c in COLUMNS}})
        self.send_error(404, "not found")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8420)
    args = ap.parse_args()
    db().close()  # create/migrate the table up front, not on the first request
    addr = ("127.0.0.1", args.port)
    httpd = ThreadingHTTPServer(addr, Handler)
    print("Dailies running at http://127.0.0.1:%d  (ctrl-C to stop)" % args.port)
    print("grades stored in %s" % DB_PATH)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
