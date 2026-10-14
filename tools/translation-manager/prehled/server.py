"""Local HTTP server: serves the UI (prehled/ui) and a small JSON API on 127.0.0.1.

Only the loopback interface is bound, the Host header is checked (DNS-rebinding protection)
and every POST needs the per-run token that the page receives from the server.
"""
import json
import mimetypes
import secrets
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .app import App, AppError
from .config import config_dir
from .project import check_project_dir
from .util import WriteFailed

UI_DIR = Path(__file__).resolve().parent / "ui"
MAX_BODY = 5 * 1024 * 1024


def log_exception():
    try:
        d = config_dir()
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "error.log", "a", encoding="utf-8") as fh:
            fh.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}\n{traceback.format_exc()}\n")
    except OSError:
        pass


class Session:
    """Per-run server state."""

    def __init__(self, app, pick_folder=None):
        self.app = app
        self.token = secrets.token_hex(16)
        self.last_ping = time.time()
        self.bye_at = None
        self.pick_folder = pick_folder


def make_handler(sess):
    app = sess.app

    def q1(query, key, default=""):
        return (query.get(key) or [default])[0]

    class Handler(BaseHTTPRequestHandler):
        server_version = "Prehled"

        def log_message(self, *args):
            pass

        # ---------------------------------------------------------- helpers
        def _host_ok(self):
            host = (self.headers.get("Host") or "").split(":")[0].lower()
            return host in ("127.0.0.1", "localhost", "[::1]")

        def _send(self, code, body, ctype):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, payload, code=200):
            self._send(code, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")

        def _static(self, name):
            path = (UI_DIR / name).resolve()
            if UI_DIR.resolve() not in path.parents or not path.is_file():
                return self._send(404, "not found", "text/plain")
            data = path.read_bytes()
            if name == "index.html":
                data = data.replace(b"__TOKEN__", sess.token.encode())
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            self._send(200, data, ctype)

        def _run(self, fn):
            try:
                with app.lock:
                    result = fn()
                self._json(result if isinstance(result, dict) else {"ok": True, "result": result})
            except AppError as e:
                self._json({"ok": False, "error": str(e)}, 400)
            except KeyError as e:
                self._json({"ok": False, "error": f"Chybí údaj: {e}"}, 400)
            except WriteFailed as e:
                self._json({"ok": False, "error": f"Nelze uložit: {e.reason} ({e.path.name})"}, 409)
            except Exception as e:  # noqa: BLE001
                log_exception()
                self._json({"ok": False, "error": f"Neočekávaná chyba: {e}"}, 500)

        # ---------------------------------------------------------- GET
        def do_GET(self):
            if not self._host_ok():
                return self._send(403, "forbidden", "text/plain")
            url = urlparse(self.path)
            q = parse_qs(url.query)
            sess.last_ping = time.time()
            sess.bye_at = None
            p = url.path
            if p in ("/", "/index.html"):
                return self._static("index.html")
            if p in ("/app.js", "/styles.css"):
                return self._static(p[1:])
            if not p.startswith("/api/"):
                return self._send(404, "not found", "text/plain")
            r = p[5:]
            if r == "ping":
                return self._json({"ok": True})
            if r == "state":
                return self._run(lambda: {
                    "ok": True, "ready": app.ready, "notices": list(app.notices),
                    "config_error": app.config.load_error, "prefs": app.ui_prefs(),
                    "project_dir": app.config.get("project_dir", "")})
            if not app.ready:
                return self._json({"ok": False, "error": "Není otevřený žádný projekt."}, 400)
            routes = {
                "overview": lambda: {"ok": True, **app.overview()},
                "files": lambda: {"ok": True, "files": app.files_payload()},
                "entries": lambda: {"ok": True, **app.entries(
                    file=q1(q, "file"), status=q1(q, "status", "all"), kind=q1(q, "kind"), q=q1(q, "q"),
                    issues=q1(q, "issues"), sort=q1(q, "sort", "line"),
                    offset=max(0, int(q1(q, "offset", "0") or 0)), limit=int(q1(q, "limit", "200") or 200),
                    around=int(q1(q, "around", "0") or 0))},
                "entry": lambda: {"ok": True, **app.entry_detail(q1(q, "file"), int(q1(q, "line", "0")))},
                "validation": lambda: {"ok": True, **app.validation_list(
                    severity=q1(q, "severity"), category=q1(q, "category"), file=q1(q, "file"), q=q1(q, "q"),
                    offset=max(0, int(q1(q, "offset", "0") or 0)), limit=int(q1(q, "limit", "200") or 200))},
                "settings": lambda: {"ok": True, **app.settings()},
                "export/preview": lambda: {"ok": True, **app.export_preview()},
            }
            fn = routes.get(r)
            if fn is None:
                return self._json({"ok": False, "error": "Neznámá adresa."}, 404)
            self._run(fn)

        # ---------------------------------------------------------- POST
        def do_POST(self):
            if not self._host_ok():
                return self._send(403, "forbidden", "text/plain")
            url = urlparse(self.path)
            if url.path == "/api/bye":      # sendBeacon cannot set headers
                if parse_qs(url.query).get("t", [""])[0] == sess.token:
                    sess.bye_at = time.time()
                return self._send(200, "ok", "text/plain")
            if self.headers.get("X-Token") != sess.token:
                return self._json({"ok": False, "error": "Zakázáno (neplatný token)."}, 403)
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length > MAX_BODY:
                    return self._json({"ok": False, "error": "Požadavek je příliš velký."}, 413)
                body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                return self._json({"ok": False, "error": "Neplatný požadavek."}, 400)
            sess.last_ping = time.time()
            r = url.path[5:] if url.path.startswith("/api/") else ""
            d = body if isinstance(body, dict) else {}

            def need_project():
                if not app.ready:
                    raise AppError("Není otevřený žádný projekt.")

            def project_set():
                path = str(d.get("path", "")).strip().strip('"')
                app.open_project(path)
                return {"ok": True}

            def project_pick():
                if sess.pick_folder is None:
                    raise AppError("Výběr složky v tomto režimu není k dispozici – zadej cestu ručně.")
                chosen = sess.pick_folder()
                if not chosen:
                    return {"ok": True, "cancelled": True}
                ok, msg = check_project_dir(chosen)
                if not ok:
                    raise AppError(msg)
                app.open_project(chosen)
                return {"ok": True, "cancelled": False, "path": chosen}

            def ints(v):
                return int(v)

            routes = {
                "project/set": project_set,
                "project/pick": project_pick,
                "refresh": lambda: {"ok": True, **app.refresh(force=bool(d.get("force")),
                                                             client_dirty=bool(d.get("dirty")),
                                                             discard=bool(d.get("discard")))},
                "file/save": lambda: app.save_file(str(d["name"]), str(d.get("c", "")), str(d.get("t", ""))),
                "assign": lambda: app.set_assign(str(d["name"]), str(d.get("v", ""))),
                "assign/suggest": lambda: {"ok": True, **app.assign_suggest(list(d.get("names") or []))},
                "assign/apply": lambda: app.assign_apply(list(d.get("items") or [])),
                "episode": lambda: app.set_episode_state(ints(d["ep"]), str(d["state"])),
                "approve/preview": lambda: {"ok": True, **app.approval_preview(
                    str(d["file"]), ints(d["line"]), str(d.get("scope", "project")), bool(d.get("same_speaker", True)))},
                "approve/apply": lambda: app.approval_apply(list(d.get("selections") or []), bool(d.get("on", True))),
                "undo": lambda: app.undo(),
                "open-editor": lambda: app.open_editor(str(d["file"]), ints(d.get("line", 1))),
                "settings": lambda: {"ok": True, **app.update_settings(d)},
                "prefs": lambda: app.set_ui_prefs(d),
                "publish/plan": lambda: {"ok": True, **app.publish_plan()},
                "publish/confirm": lambda: app.publish_confirm(str(d.get("token", "")), str(d.get("branch", ""))),
            }
            fn = routes.get(r)
            if fn is None:
                return self._json({"ok": False, "error": "Neznámá adresa."}, 404)
            if r not in ("project/set", "project/pick", "prefs", "settings"):
                try:
                    need_project()
                except AppError as e:
                    return self._json({"ok": False, "error": str(e)}, 400)
            self._run(fn)

    return Handler


def start_server(app, pick_folder=None):
    sess = Session(app, pick_folder)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(sess))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, sess, f"http://127.0.0.1:{server.server_address[1]}/"
