"""fluxora serve: a tiny standard-library HTTP server for the dashboard (localhost only).

GET  /api/run              rules.json, parity.json, repairs.json, migration.json, generated/manifest.json and the evidence summary
GET  /api/file?path=...    one generated file listed in generated/manifest.json (read-only)
GET  /runs/<id>/<file>     the run's JSON artefacts as they are on disk
POST /api/approve          {"approve": [...], "reject": [...], "all": bool}: timestamped decisions into rules.json
GET  /*                    the built dashboard from dashboard/dist
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import register
from .evidence import generated_dir_for, load_run

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIST = ROOT / "dashboard" / "dist"
DEFAULT_PORT = 8765
RUN_FILES = {"rules.json", "parity.json", "repairs.json", "migration.json", "migrated-claims.json"}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".md": "text/markdown; charset=utf-8",
}
LOCAL_ORIGINS = ("http://127.0.0.1", "http://localhost")


def make_server(run_dir: Path, *, port: int = DEFAULT_PORT, dist: Path = DASHBOARD_DIST, root: Path = ROOT) -> ThreadingHTTPServer:
    lock = threading.Lock()
    rules_path = run_dir / register.RULES_FILE

    class Handler(BaseHTTPRequestHandler):
        server_version = "Fluxora"

        def log_message(self, format, *args):  # keep the terminal quiet during the demo
            pass

        # --- GET ---------------------------------------------------------------------------------
        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/api/run":
                return self._json(200, load_run(run_dir, root))
            if url.path == "/api/file":
                return self._generated_file(parse_qs(url.query).get("path", [""])[0])
            if url.path.startswith("/runs/"):
                parts = url.path.strip("/").split("/")
                if len(parts) == 3 and parts[1] == run_dir.name and parts[2] in RUN_FILES | {"evidence.md"}:
                    target = run_dir / parts[2]
                    if target.is_file():
                        return self._bytes(200, target.read_bytes(), CONTENT_TYPES[target.suffix])
                return self._json(404, {"error": "not found"})
            return self._static(url.path)

        def _generated_file(self, rel: str):
            generated = generated_dir_for(run_dir, root)
            manifest_path = generated / "manifest.json"
            listed = {f["path"] for f in json.loads(manifest_path.read_text(encoding="utf-8"))["files"]} if manifest_path.is_file() else set()
            if rel not in listed:
                return self._json(404, {"error": "only files listed in the generated manifest can be read"})
            return self._json(200, {"path": rel, "content": (generated / rel).read_text(encoding="utf-8")})

        def _static(self, path: str):
            index = dist / "index.html"
            if not index.is_file():
                message = "Dashboard not built yet. Run: cd dashboard && npm install && npm run build"
                return self._bytes(503, message.encode("utf-8"), "text/plain; charset=utf-8")
            target = (dist / path.lstrip("/")).resolve()
            if not target.is_relative_to(dist.resolve()):
                return self._json(403, {"error": "forbidden"})
            if target.is_file():
                return self._bytes(200, target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
            if "." in Path(path).name:
                return self._json(404, {"error": "not found"})
            return self._bytes(200, index.read_bytes(), CONTENT_TYPES[".html"])  # single-page app fallback

        # --- POST --------------------------------------------------------------------------------
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > 10_000:
                self.close_connection = True
                return self._json(413, {"error": "request too large"})
            raw = self.rfile.read(length)  # always drain the body before answering, so the client sees the reply
            if urlparse(self.path).path != "/api/approve":
                return self._json(404, {"error": "not found"})
            origin = self.headers.get("Origin")
            if origin and not origin.startswith(LOCAL_ORIGINS):
                return self._json(403, {"error": "approvals are accepted from this machine only"})
            try:
                body = json.loads(raw or b"{}")
                approve = [str(r) for r in body.get("approve", [])]
                reject = [str(r) for r in body.get("reject", [])]
                approve_all = bool(body.get("all", False))
            except (ValueError, TypeError, AttributeError):
                return self._json(400, {"error": "body must be JSON: {approve: [], reject: [], all: false}"})
            with lock:
                data = register.load(rules_path)
                try:
                    decisions = register.approve(data, approve_all=approve_all, reject=reject, approve=approve)
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
                register.save(rules_path, data)
            return self._json(200, {"decisions": decisions})

        # --- helpers -----------------------------------------------------------------------------
        def _json(self, status: int, payload: dict):
            return self._bytes(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), CONTENT_TYPES[".json"])

        def _bytes(self, status: int, data: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def latest_run(runs_dir: Path) -> str | None:
    runs = sorted(p.name for p in runs_dir.iterdir() if (p / register.RULES_FILE).is_file()) if runs_dir.is_dir() else []
    return runs[-1] if runs else None
