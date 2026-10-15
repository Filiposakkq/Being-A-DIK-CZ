"""Local HTTP server: serves the UI (prehled/ui) and a small JSON API on 127.0.0.1.

Only the loopback interface is bound, the Host header is checked (DNS-rebinding protection)
and every POST needs the per-run token that the page receives from the server.
"""
import json
import mimetypes
import secrets
import socket
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from . import __version__
from .app import AppError, ProjectBusy
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
        self.windows = {}              # window id -> time of its last ping (the app quits when the last one is gone)
        self.open_window = None        # set by cli: callable(url) that opens one more app window
        self.base_url = ""


def make_handler(sess):
    app = sess.app

    def q1(query, key, default=""):
        return (query.get(key) or [default])[0]

    class Handler(BaseHTTPRequestHandler):
        server_version = "BaDIKTranslationManager"
        # Large single send() calls stalled intermittently on Windows loopback (the client got exactly
        # 65,280 bytes and then nothing), so bodies are written in small chunks.
        CHUNK = 16 * 1024

        def setup(self):
            super().setup()
            try:
                self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass

        def log_message(self, *args):
            pass

        # ---------------------------------------------------------- helpers
        def _host_ok(self):
            host = (self.headers.get("Host") or "").split(":")[0].lower()
            return host in ("127.0.0.1", "localhost", "[::1]")

        def _send(self, code, body, ctype, cache=False):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "private, max-age=600" if cache else "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:")
            self.end_headers()
            for i in range(0, len(data), self.CHUNK):
                self.wfile.write(data[i:i + self.CHUNK])

        def _drain(self):
            """Read and discard the request body before an early reply. Closing a socket that still has unread
            data makes Windows reset the connection, so the client sometimes never sees the 403 / 413."""
            try:
                n = int(self.headers.get("Content-Length", 0))
                if 0 < n <= MAX_BODY:
                    self.rfile.read(n)
                elif n > MAX_BODY:
                    self.close_connection = True
            except (ValueError, OSError):
                self.close_connection = True

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
            except ProjectBusy as e:
                self._json({"ok": False, "error": str(e), "locked": True, "path": e.path}, 409)
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
            if p in ("/app.js", "/styles.css", "/crest.svg", "/favicon.svg", "/selftest.js"):
                return self._static(p[1:])
            if not p.startswith("/api/"):
                return self._send(404, "not found", "text/plain")
            r = p[5:]
            if r == "ping":
                wid = q1(q, "w")
                if wid:
                    sess.windows[wid[:40]] = time.time()
                return self._json({"ok": True})
            if r == "state":
                return self._run(lambda: {
                    "ok": True, "ready": app.ready, "notices": list(app.notices),
                    "config_error": app.config.load_error, "prefs": app.ui_prefs(), "version": __version__,
                    "project_dir": app.config.get("project_dir", "")})
            if not app.ready:
                return self._json({"ok": False, "error": "Není otevřený žádný projekt."}, 400)
            if r == "game/image":              # a picture from the game archives, by the key the index returned (never a path)
                try:
                    with app.lock:
                        data, mime = app.game_image(q1(q, "k"))
                except AppError as e:
                    return self._send(404, str(e), "text/plain")
                except Exception:  # noqa: BLE001
                    log_exception()
                    return self._send(500, "chyba", "text/plain")
                return self._send(200, data, mime, cache=True)
            routes = {
                "overview": lambda: {"ok": True, **app.overview()},
                "files": lambda: {"ok": True, "files": app.files_payload()},
                "entries": lambda: {"ok": True, **app.entries(
                    file=q1(q, "file"), status=q1(q, "status", "all"), kind=q1(q, "kind"), q=q1(q, "q"),
                    issues=q1(q, "issues"), sort=q1(q, "sort", "line"),
                    offset=max(0, int(q1(q, "offset", "0") or 0)), limit=int(q1(q, "limit", "200") or 200),
                    around=int(q1(q, "around", "0") or 0), unit=q1(q, "unit"))},
                "entry": lambda: {"ok": True, **app.entry_detail(q1(q, "file"), int(q1(q, "line", "0")))},
                "validation": lambda: {"ok": True, **app.validation_list(
                    severity=q1(q, "severity"), category=q1(q, "category"), file=q1(q, "file"), q=q1(q, "q"),
                    offset=max(0, int(q1(q, "offset", "0") or 0)), limit=int(q1(q, "limit", "200") or 200),
                    ignored=q1(q, "ignored", "hide"), group=q1(q, "group"))},
                "ignore/list": lambda: {"ok": True, **app.ignored_list()},
                "settings": lambda: {"ok": True, **app.settings()},
                "fix/last": lambda: {"ok": True, **app.fix_last()},
                "game/scene": lambda: {"ok": True, **app.scene_info(q1(q, "file"), int(q1(q, "line", "0")))},
                "entry/scene": lambda: {"ok": True, **app.entry_scene(q1(q, "file"), int(q1(q, "line", "0")), int(q1(q, "radius", "6") or 6))},
                "snapshots": lambda: {"ok": True, **app.snapshot_list()},
                "snapshots/files": lambda: {"ok": True, **app.snapshot_files(q1(q, "name"))},
                "lint/status": lambda: {"ok": True, **app.lint_status()},
                "entry/history": lambda: {"ok": True, **app.entry_history(q1(q, "file"), int(q1(q, "line", "0")))},
                "entry/memory": lambda: {"ok": True, **app.entry_memory(q1(q, "file"), int(q1(q, "line", "0")))},
                "consistency": lambda: {"ok": True, **app.consistency(q1(q, "loose") == "1", q1(q, "by_speaker") == "1")},
                "entry/context": lambda: {"ok": True, **app.entry_context(q1(q, "file"), int(q1(q, "line", "0")))},
                "glossary/occurrences": lambda: {"ok": True, **app.glossary_occurrences(
                    q1(q, "code"), q1(q, "missing") == "1")},
                "glossary": lambda: {"ok": True, **app.glossary_payload()},
                "proof/next": lambda: {"ok": True, **app.proof_next(q1(q, "file"), int(q1(q, "after", "0") or 0))},
                "export/preview": lambda: {"ok": True, **app.export_preview()},
            }
            fn = routes.get(r)
            if fn is None:
                return self._json({"ok": False, "error": "Neznámá adresa."}, 404)
            self._run(fn)

        # ---------------------------------------------------------- POST
        def do_POST(self):
            if not self._host_ok():
                self._drain()
                return self._send(403, "forbidden", "text/plain")
            url = urlparse(self.path)
            if url.path == "/api/bye":      # sendBeacon cannot set headers
                qs = parse_qs(url.query)
                if qs.get("t", [""])[0] == sess.token:
                    sess.windows.pop(qs.get("w", [""])[0][:40], None)
                    now = time.time()
                    for k in [k for k, t in sess.windows.items() if now - t > 30]:      # windows that stopped pinging
                        sess.windows.pop(k, None)
                    if not sess.windows:
                        sess.bye_at = now
                return self._send(200, "ok", "text/plain")
            if self.headers.get("X-Token") != sess.token:
                self._drain()
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
                app.open_project(path, force=bool(d.get("force")))
                app.maybe_auto_snapshot()
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

            def open_window():
                """One more app window with its own list / filter state, e.g. to read the scene next to the editor."""
                if sess.open_window is None:
                    return {"ok": False, "fallback": True, "error": "Nové okno tu nejde otevřít z aplikace."}
                q = {"win": "2"}
                if str(d.get("view", "")) in ("overview", "files", "entries", "validation", "glossary", "publish", "settings"):
                    q["view"] = str(d["view"])
                if d.get("file"):
                    q["file"] = str(d["file"])[:500]
                if str(d.get("line", "")).isdigit():
                    q["line"] = str(int(d["line"]))
                if str(d.get("status", "")) in ("all", "todo", "translated", "approved", "review", "proofed", "fix", "stale"):
                    q["status"] = str(d["status"])
                url = sess.base_url + "?" + urlencode(q)
                try:
                    sess.open_window(url)
                except Exception as e:  # noqa: BLE001
                    return {"ok": False, "fallback": True, "error": f"Okno se nepodařilo otevřít ({e})."}
                return {"ok": True, "url": url}

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
                "glossary/set": lambda: app.glossary_set(list(d.get("items") or [])),
                "glossary/import-preview": lambda: {"ok": True, **app.glossary_import_preview(str(d.get("path", "")))},
                "glossary/import-apply": lambda: app.glossary_import_apply(list(d.get("items") or [])),
                "glossary/delete": lambda: app.glossary_delete(list(d.get("codes") or [])),
                "proof/set": lambda: app.proof_set(list(d.get("items") or []), str(d.get("state", "ok")),
                                                   d.get("note")),
                "proof/upto": lambda: app.proof_upto(str(d["file"]), ints(d["line"]), str(d.get("state", "ok"))),
                "proof/clear-file": lambda: app.proof_clear_file(str(d["file"])),
                "open-url": lambda: app.open_link(str(d.get("id", ""))),
                "window/open": lambda: open_window(),
                "fix/preview": lambda: {"ok": True, **app.fix_preview(list(d.get("items") or []), str(d.get("file", "")), list(d.get("kinds") or []))},
                "replace/preview": lambda: {"ok": True, **app.replace_preview(d.get("find", ""), d.get("replace", ""), str(d.get("mode", "plain")), bool(d.get("case")), list(d.get("files") or []), bool(d.get("protect", True)))},
                "replace/apply": lambda: app.replace_apply(list(d.get("selections") or []), d.get("find", ""), d.get("replace", ""), str(d.get("mode", "plain")), bool(d.get("case")), list(d.get("files") or []), bool(d.get("protect", True))),
                "fix/apply": lambda: app.fix_apply(list(d.get("items") or []), str(d.get("file", "")), list(d.get("kinds") or []),
                                                  list(d["selections"]) if d.get("selections") is not None else None),
                "fix/undo": lambda: app.fix_undo(),
                "entry/mt": lambda: {"ok": True, **app.mt_suggest(str(d["file"]), ints(d["line"]))},
                "mt/targets": lambda: {"ok": True, **app.mt_targets(str(d.get("file", "")), d.get("lines") or None, bool(d.get("only_todo", True)))},
                "mt/batch": lambda: {"ok": True, **app.mt_batch(d.get("items") or [])},
                "mt/apply": lambda: app.mt_apply(d.get("selections") or []),
                "snapshots/create": lambda: app.snapshot_create(),
                "snapshots/restore": lambda: app.snapshot_restore(str(d.get("name", "")), d.get("files")),
                "snapshots/delete": lambda: app.snapshot_delete(str(d.get("name", ""))),
                "lint/start": lambda: app.lint_start(),
                "consistency/unify": lambda: app.consistency_unify(str(d.get("key", "")), str(d.get("target", "")), d.get("lines"), bool(d.get("loose")), bool(d.get("by_speaker"))),
                "ignore/set": lambda: app.ignore_set(list(d.get("items") or []), bool(d.get("on", True)), str(d.get("note", ""))),
                "entry/check": lambda: {"ok": True, **app.entry_check(str(d["file"]), ints(d["line"]), str(d.get("text", "")))},
                "entry/save": lambda: app.entry_save(str(d["file"]), ints(d["line"]), str(d.get("text", ""))),
                "approve/rules": lambda: {"ok": True, **app.rule_preview(d.get("rules") or [], list(d.get("files") or []))},
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
            if r not in ("project/set", "project/pick", "prefs", "settings", "open-url"):
                try:
                    need_project()
                except AppError as e:
                    return self._json({"ok": False, "error": str(e)}, 400)
            self._run(fn)

    return Handler


class LocalServer(ThreadingHTTPServer):
    """The default listen backlog (5) drops connections when a browser opens many in parallel
    (page + script + style + API calls), which showed up as sporadic ERR_CONNECTION_RESET."""
    request_queue_size = 128
    daemon_threads = True


def start_server(app, pick_folder=None):
    sess = Session(app, pick_folder)
    server = LocalServer(("127.0.0.1", 0), make_handler(sess))
    sess.base_url = f"http://127.0.0.1:{server.server_address[1]}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, sess, sess.base_url
