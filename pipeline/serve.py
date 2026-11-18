"""Self-hosted server for Dailies: localhost only, stdlib-only, no deps.

    python3 pipeline/serve.py                 # http://localhost:8420
    python3 pipeline/serve.py --port 9000
    python3 pipeline/serve.py --lan           # also reachable from your phone on the same wifi

Routes:
  /                              -> the active (or only) profile
  /p/<profile>/                  -> that profile's mix reel (or its only pool)
  /p/<profile>/<pool>/           -> one pool's reel
  /posters/<slug>.jpg            -> shared poster cache
  /api/profiles                  -> [{name, pools}]
  /api/p/<profile>/grades        GET all verdicts · POST /grades/<slug> to set one
  /api/p/<profile>/reweigh       GET status · POST ?pool=<pool|mix> to run the pipeline

Grades land in profiles/<profile>/grades.db: one row per film with the full
seen/unseen verdict the page sends ({slug, title, grade, status, rating,
interest, never, pool, ts} -- see common.verdict; `pool` is the reel it was
graded in).
"""
import argparse
import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

POSTERS = os.path.join(common.DATA, "posters")
PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable


def valid_profile(name):
    return bool(common.NAME_RE.match(name or "")) and name in common.list_profiles()


def valid_pool(profile, name):
    return bool(common.NAME_RE.match(name or "")) and name in common.pools(profile)


# label, script, extra env, soft (a nonzero exit is logged and skipped rather
# than aborting -- grading-feedback steps are refinements, not required to
# produce a new reel), extra args.
def _pool_steps(profile, pool):
    P = common.paths(profile, pool)
    iter_n = common.next_iteration(P.reports)
    env = {"CINESCOPE_PROFILE": profile, "CINESCOPE_POOL": pool}
    e = lambda **kw: dict(env, **kw)
    return [
        ("%s: pull grades" % pool,    "pull_grades.py",   e(),            True),
        ("%s: tune weights" % pool,   "tune.py",          e(),            True, ["--apply"]),
        ("%s: promote seeds" % pool,  "promote_seeds.py", e(),            True),
        ("%s: crawl" % pool,          "crawl.py",         e(),            False),
        ("%s: score" % pool,          "score.py",         e(),            False),
        ("%s: report" % pool,         "report.py",        e(ITER=iter_n), True),
        ("%s: fetch posters" % pool,  "fetch_posters.py", e(),            True),
        ("%s: build ui" % pool,       "build_ui.py",      e(ITER=iter_n, MODE="local"), False),
    ]


def _pipeline_steps(profile, pool):
    names = common.pools(profile) if pool == common.MIX else [pool]
    steps = []
    for name in names:
        steps += _pool_steps(profile, name)
    env = {"CINESCOPE_PROFILE": profile}
    steps.append(("update keepers", "update_keepers.py",
                  dict(env, CINESCOPE_POOL=names[0]), True))
    if len(common.pools(profile)) > 1:
        steps.append(("build mix", "build_ui.py",
                      dict(env, CINESCOPE_POOL=common.MIX, MODE="local"), True))
    return steps


pipeline_lock = threading.Lock()
pipeline_state = {"running": False, "log": [], "error": None, "step": None,
                  "profile": None, "pool": None, "started_at": None, "done_at": None}


def _log(line):
    with pipeline_lock:
        pipeline_state["log"].append(line)
        pipeline_state["log"] = pipeline_state["log"][-500:]  # a status feed, not an archive


def _run_step(label, script, env_extra, args=None):
    _log("== %s ==" % label)
    with pipeline_lock:
        pipeline_state["step"] = label
    env = dict(os.environ)
    env.update(env_extra)
    cmd = [PYTHON, os.path.join(PIPELINE_DIR, script)] + (args or [])
    proc = subprocess.Popen(cmd, cwd=PIPELINE_DIR, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in proc.stdout:
        _log(line.rstrip())
    proc.wait()
    return proc.returncode


def _run_pipeline(profile, pool):
    try:
        for step in _pipeline_steps(profile, pool):
            label, script, env_extra, soft = step[:4]
            args = step[4] if len(step) > 4 else None
            rc = _run_step(label, script, env_extra, args)
            if rc != 0:
                _log("-- %s exited %d%s --" % (label, rc, " (continuing, non-essential)" if soft else ""))
                if not soft:
                    with pipeline_lock:
                        pipeline_state["error"] = "%s failed (exit %d) -- see log above" % (label, rc)
                    return
        _log("== done ==")
    except Exception as e:
        _log("!! crashed: %s" % e)
        with pipeline_lock:
            pipeline_state["error"] = str(e)
    finally:
        with pipeline_lock:
            pipeline_state["running"] = False
            pipeline_state["step"] = None
            pipeline_state["done_at"] = time.time()


def start_pipeline(profile, pool):
    with pipeline_lock:
        if pipeline_state["running"]:
            return False
        pipeline_state.update(running=True, log=[], error=None, step=None, profile=profile,
                              pool=pool, started_at=time.time(), done_at=None)
    threading.Thread(target=_run_pipeline, args=(profile, pool), daemon=True).start()
    return True


NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>Dailies</title>
<body style="font:15px/1.5 system-ui;max-width:620px;margin:60px auto;padding:0 16px">
<h2>No reel yet for %s</h2>
<p>Build one first:</p>
<pre style="background:#eee;padding:12px;border-radius:8px">./run.sh %s %s</pre>
<p>then reload this page.</p></body>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "DailiesLocal/3"

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, where):
        self.send_response(302)
        self.send_header("Location", where)
        self.end_headers()

    def _html(self, text, code=200):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
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
        self.send_header("Cache-Control", "no-cache" if ctype.startswith("text/html") else "max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def _page(self, profile, pool=None):
        names = common.pools(profile)
        if pool is None:
            if len(names) > 1:
                path = os.path.join(common.profile_dir(profile), "dailies.html")
                if os.path.exists(path):
                    return self._file(path, "text/html; charset=utf-8")
            pool = common.pool_name(profile) if names else None
            if pool is None:
                return self._html(NOT_BUILT % (profile, profile, "") , 404)
            return self._redirect("/p/%s/%s/" % (profile, pool))
        path = common.paths(profile, pool).dailies
        if not os.path.exists(path):
            return self._html(NOT_BUILT % ("%s / %s" % (profile, pool), profile, pool), 404)
        return self._file(path, "text/html; charset=utf-8")

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        parts = [urllib.parse.unquote(p) for p in parsed.path.split("/") if p]

        if not parts:
            try:
                return self._redirect("/p/%s/" % common.profile_name())
            except SystemExit as e:
                return self._html("<pre>%s</pre>" % e, 404)

        if parts[0] == "posters" and len(parts) == 2:
            safe = os.path.basename(parts[1])  # no path traversal
            return self._file(os.path.join(POSTERS, safe), "image/jpeg")

        if parts[0] == "p" and len(parts) in (2, 3):
            if not valid_profile(parts[1]):
                return self.send_error(404, "no such profile")
            if len(parts) == 3:
                if not valid_pool(parts[1], parts[2]):
                    return self.send_error(404, "no such pool")
                return self._page(parts[1], parts[2])
            return self._page(parts[1])

        if parts == ["api", "profiles"]:
            return self._json(200, [{"name": n, "pools": common.pools(n)}
                                    for n in common.list_profiles()])

        if len(parts) == 4 and parts[:2] == ["api", "p"] and valid_profile(parts[2]):
            profile = parts[2]
            if parts[3] == "grades":
                rows = common.read_db_grades(profile)
                return self._json(200, [dict(r, never=bool(r.get("never"))) for r in rows.values()])
            if parts[3] == "reweigh":
                with pipeline_lock:
                    st = dict(pipeline_state)
                mine = st["profile"] == profile
                return self._json(200, {
                    "running": st["running"] and mine, "busy_elsewhere": st["running"] and not mine,
                    "step": st["step"] if mine else None, "error": st["error"] if mine else None,
                    "log": st["log"][-120:] if mine else [], "pool": st["pool"] if mine else None,
                    "started_at": st["started_at"], "done_at": st["done_at"],
                })

        self.send_error(404, "not found")

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        parts = [urllib.parse.unquote(p) for p in parsed.path.split("/") if p]
        query = urllib.parse.parse_qs(parsed.query)
        if len(parts) < 4 or parts[:2] != ["api", "p"] or not valid_profile(parts[2]):
            return self.send_error(404, "not found")
        profile = parts[2]

        if len(parts) == 5 and parts[3] == "grades":
            slug = parts[4]
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json(400, {"error": "bad json"})
            pool = body.get("pool")
            row = {
                "slug": slug, "title": body.get("title") or slug,
                "grade": body.get("grade"), "status": body.get("status"),
                "rating": body.get("rating"), "interest": body.get("interest"),
                "never": 1 if body.get("never") else 0,
                "pool": pool if valid_pool(profile, pool) else None,
                "ts": int(time.time() * 1000),
            }
            cols = common.GRADE_DB_COLUMNS
            conn = common.grades_db(profile)
            conn.execute(
                "INSERT INTO grades(%s) VALUES (%s) ON CONFLICT(slug) DO UPDATE SET %s"
                % (", ".join(cols), ", ".join("?" * len(cols)),
                   ", ".join("%s=excluded.%s" % (c, c) for c in cols if c != "slug")),
                [row[c] for c in cols])
            conn.commit()
            conn.close()
            return self._json(200, dict(row, ok=True))

        if len(parts) == 4 and parts[3] == "reweigh":
            pool = (query.get("pool") or [common.MIX])[0]
            if pool != common.MIX and not valid_pool(profile, pool):
                return self._json(400, {"error": "no such pool"})
            if not start_pipeline(profile, pool):
                return self._json(409, {"error": "already running"})
            return self._json(200, {"ok": True, "started": True})

        self.send_error(404, "not found")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8420)
    ap.add_argument("--lan", action="store_true", help="listen on all interfaces, not just localhost")
    args = ap.parse_args()
    addr = ("0.0.0.0" if args.lan else "127.0.0.1", args.port)
    httpd = ThreadingHTTPServer(addr, Handler)
    print("Dailies running at http://127.0.0.1:%d  (ctrl-C to stop)" % args.port)
    print("profiles: %s" % (", ".join(common.list_profiles()) or
                            "none yet -- python3 pipeline/profiles.py new <name>"))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
