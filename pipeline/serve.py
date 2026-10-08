"""Self-hosted server for Dailies: localhost only, stdlib-only, no deps.

Serves the static page + poster images, and a tiny JSON API backing the
grading state that pipeline/build_ui.py's MODE=local variant writes to.

    python3 pipeline/serve.py            # http://localhost:8420
    python3 pipeline/serve.py --port 9000

Grades land in data/grades.db (sqlite3, stdlib) -- same shape pull_grades.py
already expects, so the rest of the tuning pipeline doesn't change at all.
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


def db():
    os.makedirs(common.DATA, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS grades(
        slug TEXT PRIMARY KEY, title TEXT, grade INTEGER, seen INTEGER, ts INTEGER
    )""")
    return conn


class Handler(BaseHTTPRequestHandler):
    server_version = "DailiesLocal/1"

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
            rows = conn.execute("SELECT slug, title, grade, seen, ts FROM grades").fetchall()
            conn.close()
            return self._json(200, [
                {"slug": s, "title": t, "grade": g, "seen": bool(sn), "ts": ts}
                for s, t, g, sn, ts in rows
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
            grade = body.get("grade")
            seen = 1 if body.get("seen") else 0
            title = body.get("title") or slug
            conn = db()
            conn.execute(
                """INSERT INTO grades(slug, title, grade, seen, ts) VALUES (?,?,?,?,?)
                   ON CONFLICT(slug) DO UPDATE SET
                     title=excluded.title, grade=excluded.grade,
                     seen=excluded.seen, ts=excluded.ts""",
                (slug, title, grade, seen, int(time.time() * 1000)),
            )
            conn.commit()
            conn.close()
            return self._json(200, {"ok": True, "slug": slug, "grade": grade, "seen": bool(seen)})
        self.send_error(404, "not found")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8420)
    args = ap.parse_args()
    db().close()  # create the table up front so the first request isn't the migration
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
