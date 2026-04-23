from __future__ import annotations

import json
import os
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_DASHBOARD_DIST = Path(__file__).parent.parent / "dashboard" / "dist"
_DASHBOARD_HTML = Path(__file__).parent.parent / "legacy_dashboard" / "dashboard.html"
_IGNORED_DIRS = {"node_modules", ".git", ".pytest_cache", "__pycache__", "dist"}


def _is_hidden_bundle_path(path: Path) -> bool:
    parent_name = path.parent.name.lower()
    return parent_name.startswith("_warmup_") or "__warmup_" in parent_name


def _provenance_metadata(manifest: dict) -> dict:
    provenance = manifest.get("provenance") if isinstance(manifest.get("provenance"), dict) else {}
    runtime = provenance.get("runtime") if isinstance(provenance.get("runtime"), dict) else {}
    git = provenance.get("git") if isinstance(provenance.get("git"), dict) else {}
    return {
        "workflowTier": provenance.get("workflow_tier"),
        "engineBackend": runtime.get("engine_backend"),
        "monteCarloBackend": runtime.get("monte_carlo_backend"),
        "parallelism": runtime.get("parallelism"),
        "workerCount": runtime.get("worker_count"),
        "gitCommit": git.get("commit"),
        "gitDirty": git.get("dirty"),
    }


def _registry_seed(row: dict) -> dict:
    return {
        "name": row.get("run_name"),
        "runName": row.get("run_name"),
        "type": row.get("run_type"),
        "profile": row.get("output_profile"),
        "finalPnl": row.get("final_pnl"),
        "createdAt": row.get("created_at"),
        "workflowTier": row.get("workflow_tier"),
        "engineBackend": row.get("engine_backend"),
        "monteCarloBackend": row.get("monte_carlo_backend"),
        "parallelism": row.get("parallelism"),
        "workerCount": row.get("worker_count"),
        "gitCommit": row.get("git_commit"),
        "gitDirty": row.get("git_dirty"),
        "source": "registry",
    }


def _dashboard_metadata(path: Path) -> dict:
    """Read lightweight bundle metadata without loading large dashboard payloads."""
    metadata = {
        "name": path.parent.name,
        "runName": path.parent.name,
        "type": "unknown",
        "profile": None,
        "finalPnl": None,
        "createdAt": None,
        "sizeBytes": path.stat().st_size,
        "dashboardSizeBytes": path.stat().st_size,
        "fileCount": None,
        "workflowTier": None,
        "engineBackend": None,
        "monteCarloBackend": None,
        "parallelism": None,
        "workerCount": None,
        "gitCommit": None,
        "gitDirty": None,
        "source": "dashboard",
    }
    manifest_path = path.with_name("manifest.json")
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        summary = manifest.get("summary") if isinstance(manifest.get("summary"), dict) else {}
        run_name = manifest.get("run_name") or metadata["name"]
        output_profile = manifest.get("output_profile") if isinstance(manifest.get("output_profile"), dict) else {}
        bundle_stats = manifest.get("bundle_stats") if isinstance(manifest.get("bundle_stats"), dict) else {}
        metadata.update(
            {
                "name": run_name,
                "runName": run_name,
                "type": manifest.get("run_type") or manifest.get("mode") or metadata["type"],
                "profile": output_profile.get("profile"),
                "finalPnl": summary.get("final_pnl"),
                "createdAt": manifest.get("created_at"),
                "sizeBytes": bundle_stats.get("total_size_bytes") or metadata["sizeBytes"],
                "fileCount": bundle_stats.get("file_count"),
                "source": "manifest",
            }
        )
        metadata.update(_provenance_metadata(manifest))
        return metadata

    if metadata["dashboardSizeBytes"] > 5_000_000:
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
            "profile": (meta.get("outputProfile") or {}).get("profile") if isinstance(meta.get("outputProfile"), dict) else None,
            "finalPnl": summary.get("final_pnl"),
            "createdAt": meta.get("createdAt"),
            "workflowTier": (meta.get("provenance") or {}).get("workflow_tier") if isinstance(meta.get("provenance"), dict) else None,
            "engineBackend": ((meta.get("provenance") or {}).get("runtime") or {}).get("engine_backend") if isinstance((meta.get("provenance") or {}).get("runtime"), dict) else None,
            "monteCarloBackend": ((meta.get("provenance") or {}).get("runtime") or {}).get("monte_carlo_backend") if isinstance((meta.get("provenance") or {}).get("runtime"), dict) else None,
            "parallelism": ((meta.get("provenance") or {}).get("runtime") or {}).get("parallelism") if isinstance((meta.get("provenance") or {}).get("runtime"), dict) else None,
            "workerCount": ((meta.get("provenance") or {}).get("runtime") or {}).get("worker_count") if isinstance((meta.get("provenance") or {}).get("runtime"), dict) else None,
            "gitCommit": ((meta.get("provenance") or {}).get("git") or {}).get("commit") if isinstance((meta.get("provenance") or {}).get("git"), dict) else None,
            "gitDirty": ((meta.get("provenance") or {}).get("git") or {}).get("dirty") if isinstance((meta.get("provenance") or {}).get("git"), dict) else None,
        }
    )
    return metadata


def _walk_candidates(root: Path, filename: str, max_depth: int) -> list[Path]:
    results: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in _IGNORED_DIRS]
        current = Path(dirpath)
        try:
            rel_dir = current.relative_to(root)
        except ValueError:
            continue
        if len(rel_dir.parts) > max_depth:
            dirnames[:] = []
            continue
        if filename in filenames:
            results.append(current / filename)
    return sorted(results)


def _registry_candidates(root: Path, max_depth: int) -> dict[str, dict]:
    candidates: dict[str, dict] = {}
    for registry_path in _walk_candidates(root, "run_registry.jsonl", max_depth):
        try:
            lines = registry_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            dashboard_json = row.get("dashboard_json")
            output_dir = row.get("output_dir")
            target = None
            if dashboard_json:
                target = Path(str(dashboard_json))
            elif output_dir:
                target = Path(str(output_dir)) / "dashboard.json"
            if target is None:
                continue
            try:
                resolved = target.resolve()
                rel = resolved.relative_to(root.resolve())
            except (OSError, ValueError):
                continue
            if len(rel.parts) > max_depth + 1 or not resolved.is_file():
                continue
            candidates[str(rel).replace("\\", "/")] = _registry_seed(row)
    return candidates


def _find_bundles(root: Path, max_depth: int = 4) -> list[dict]:
    """Walk up to max_depth levels looking for dashboard.json files."""
    results = []
    root = root.resolve()
    candidate_meta = _registry_candidates(root, max_depth)
    for path in _walk_candidates(root, "dashboard.json", max_depth):
        if _is_hidden_bundle_path(path):
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if len(rel.parts) > max_depth + 1:
            continue
        candidate_meta.setdefault(str(rel).replace("\\", "/"), {})
    for rel_path, seed in sorted(candidate_meta.items()):
        path = (root / rel_path).resolve()
        if _is_hidden_bundle_path(path):
            continue
        if not path.is_file():
            continue
        metadata = _dashboard_metadata(path)
        for key, value in seed.items():
            if metadata.get(key) in (None, "", "unknown") and value not in (None, ""):
                metadata[key] = value
        metadata["path"] = rel_path
        results.append(metadata)
    results.sort(key=lambda row: ((row.get("createdAt") or ""), str(row.get("path") or "")), reverse=True)
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

        # Fallback for environments where the React build has not been produced.
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


def serve_directory(
    directory: Path,
    host: str = "127.0.0.1",
    port: int = 5555,
    *,
    open_browser: bool = False,
    query: str | None = None,
) -> None:
    directory = directory.resolve()

    class Handler(_Handler):
        root = directory

    with HTTPServer((host, port), Handler) as httpd:
        base_path = "/" if _DASHBOARD_DIST.is_dir() else "/dashboard.html"
        url = f"http://{host}:{port}{base_path}"
        if query:
            url = f"{url}?{query}"
        print(f"Serving {directory} at {url}")
        print(f"  API: http://{host}:{port}/api/runs")
        if open_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("Shutting down dashboard server")
