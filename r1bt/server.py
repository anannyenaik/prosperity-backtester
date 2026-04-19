from __future__ import annotations

import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_DASHBOARD_DIST = Path(__file__).parent.parent / "dashboard" / "dist"
_DASHBOARD_HTML = Path(__file__).parent.parent / "visualizer" / "dashboard.html"


def _dashboard_metadata(path: Path) -> dict:
    """Read lightweight bundle metadata without loading large dashboard payloads."""
    metadata = {
        "name": path.parent.name,
        "runName": path.parent.name,
        "type": "unknown",
        "finalPnl": None,
        "createdAt": None,
        "sizeBytes": path.stat().st_size,
    }
    manifest_path = path.with_name("manifest.json")
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        summary = manifest.get("summary") if isinstance(manifest.get("summary"), dict) else {}
        run_name = manifest.get("run_name") or metadata["name"]
        metadata.update(
            {
                "name": run_name,
                "runName": run_name,
                "type": manifest.get("run_type") or manifest.get("mode") or metadata["type"],
                "finalPnl": summary.get("final_pnl"),
                "createdAt": manifest.get("created_at"),
            }
        )
        return metadata

    if metadata["sizeBytes"] > 5_000_000:
        return metadata

    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return metadata

    summary = payload.get("summary") or {}
    meta = payload.get("meta") or {}
    run_name = meta.get("runName") or metadata["name"]
    metadata.update(
        {
            "name": run_name,
            "runName": run_name,
            "type": payload.get("type", metadata["type"]),
            "finalPnl": summary.get("final_pnl"),
            "createdAt": meta.get("createdAt"),
        }
    )
    return metadata


def _find_bundles(root: Path, max_depth: int = 4) -> list[dict]:
    """Walk up to max_depth levels looking for dashboard.json files."""
    results = []
    ignored_dirs = {"node_modules", ".git", ".pytest_cache", "__pycache__", "dist"}
    candidates: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in ignored_dirs]
        current = Path(dirpath)
        try:
            rel_dir = current.relative_to(root)
        except ValueError:
            continue
        if len(rel_dir.parts) > max_depth:
            dirnames[:] = []
            continue
        if "dashboard.json" in filenames:
            candidates.append(current / "dashboard.json")
    for p in sorted(candidates):
        if any((ancestor / "dashboard.json").is_file() for ancestor in p.parents if ancestor != p.parent and ancestor != root.parent):
            continue
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if len(rel.parts) > max_depth + 1:
            continue
        metadata = _dashboard_metadata(p)
        metadata["path"] = str(rel).replace("\\", "/")
        results.append(metadata)
    return results


class _Handler(BaseHTTPRequestHandler):
    root: Path

    def log_message(self, fmt: str, *args: object) -> None:  # silence access log
        pass

    def _send_json(self, obj: object, status: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_404(self) -> None:
        self.send_response(404)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # API routes
        if path == "/api/runs":
            self._send_json(_find_bundles(self.root))
            return

        if path.startswith("/api/run/"):
            rel = urllib.parse.unquote(path[len("/api/run/"):])
            target = (self.root / rel).resolve()
            # Ensure the resolved path is still under root (path traversal guard)
            try:
                target.relative_to(self.root.resolve())
            except ValueError:
                self._send_json({"error": "forbidden"}, 403)
                return
            if not target.is_file():
                self._send_json({"error": "not found"}, 404)
                return
            try:
                with target.open() as f:
                    data = json.load(f)
                self._send_json(data)
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
            return

        # Static files: serve built dashboard if available
        if _DASHBOARD_DIST.is_dir():
            # Map URL path to dist file, SPA fallback to index.html
            if path == "/" or path == "":
                file_path = _DASHBOARD_DIST / "index.html"
            else:
                file_path = _DASHBOARD_DIST / path.lstrip("/")

            if not file_path.exists() or file_path.is_dir():
                file_path = _DASHBOARD_DIST / "index.html"

            if file_path.exists():
                ct = _content_type(file_path)
                self._send_file(file_path, ct)
                return

        # Fallback: serve legacy visualizer
        if _DASHBOARD_HTML.is_file():
            self._send_file(_DASHBOARD_HTML, "text/html")
            return

        self._send_404()


def _content_type(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".html": "text/html",
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
        ".woff2": "font/woff2",
        ".woff": "font/woff",
        ".ttf": "font/ttf",
    }.get(ext, "application/octet-stream")


def serve_directory(directory: Path, host: str = "127.0.0.1", port: int = 5555) -> None:
    directory = directory.resolve()

    class Handler(_Handler):
        root = directory

    with HTTPServer((host, port), Handler) as httpd:
        if _DASHBOARD_DIST.is_dir():
            url = f"http://{host}:{port}/"
        else:
            url = f"http://{host}:{port}/dashboard.html"
        print(f"Serving {directory} at {url}")
        print(f"  API: http://{host}:{port}/api/runs")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("Shutting down dashboard server")
