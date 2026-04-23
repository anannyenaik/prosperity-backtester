from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import platform
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[1]
    repo_root_text = str(repo_root)
    if repo_root_text not in sys.path:
        sys.path.insert(0, repo_root_text)

from analysis.benchmark_runtime import _git_text  # noqa: E402


def _default_bundle(repo_root: Path) -> Path:
    candidates = sorted(
        (
            path
            for path in (repo_root / "backtests").rglob("mc_ceiling_light_w8/dashboard.json")
            if "runtime" in {part.lower() for part in path.parts}
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    return repo_root / "backtests" / "runtime_benchmark" / "cases" / "mc_ceiling_light_w8" / "dashboard.json"


def _default_output_dir(repo_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return repo_root / "backtests" / f"{timestamp}_architecture_bakeoff"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run architecture bake-off microbenchmarks on a real dashboard payload")
    parser.add_argument("--repo-root", default=".", help="Repo root")
    parser.add_argument("--bundle", default=None, help="Path to a dashboard.json payload to benchmark")
    parser.add_argument("--output-dir", default=None, help="Directory for the generated report")
    parser.add_argument("--workers", type=int, default=8, help="Worker count for the transport microbenchmark")
    parser.add_argument("--tasks", type=int, default=32, help="Task count for the transport microbenchmark")
    parser.add_argument("--repeats", type=int, default=3, help="Repeats for serialisation timings")
    return parser


def _time_call(fn, repeats: int) -> tuple[float, object]:
    best = None
    last_value = None
    for _ in range(max(1, int(repeats))):
        started = time.perf_counter()
        last_value = fn()
        elapsed = time.perf_counter() - started
        best = elapsed if best is None else min(best, elapsed)
    return float(best or 0.0), last_value


def _checksum_stride(data: bytes | memoryview, step: int = 4096) -> int:
    view = data if isinstance(data, memoryview) else memoryview(data)
    return int(sum(view[::step]))


def _worker_checksum_bytes(payload: bytes) -> int:
    return _checksum_stride(payload)


def _worker_checksum_shared(name: str, size: int) -> int:
    shared = SharedMemory(name=name)
    try:
        return _checksum_stride(shared.buf[:size])
    finally:
        shared.close()


def _worker_checksum_shared_tuple(args: tuple[str, int]) -> int:
    return _worker_checksum_shared(*args)


def _transport_benchmark(payload: bytes, *, workers: int, tasks: int) -> dict[str, object]:
    context = mp.get_context("spawn")

    def run_pickle() -> list[int]:
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
            return list(pool.map(_worker_checksum_bytes, [payload] * tasks))

    def run_shared() -> list[int]:
        shared = SharedMemory(create=True, size=len(payload))
        try:
            shared.buf[: len(payload)] = payload
            with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
                args = [(shared.name, len(payload))] * tasks
                return list(pool.map(_worker_checksum_shared_tuple, args))
        finally:
            shared.close()
            shared.unlink()

    pickle_seconds, pickle_checksums = _time_call(run_pickle, 1)
    shared_seconds, shared_checksums = _time_call(run_shared, 1)

    return {
        "payload_bytes": len(payload),
        "workers": int(workers),
        "tasks": int(tasks),
        "pickle_seconds": round(pickle_seconds, 3),
        "shared_memory_seconds": round(shared_seconds, 3),
        "speedup_ratio": None if shared_seconds <= 0 else round(pickle_seconds / shared_seconds, 3),
        "checksums_match": pickle_checksums == shared_checksums,
    }


def _render_markdown(report: dict[str, object]) -> str:
    serial = report["serialisation"]
    transport = report["transport"]
    lines = [
        "# Architecture Bake-off",
        "",
        "Fixture",
        f"- Repo root: `{report['repo_root']}`",
        f"- Git commit: `{report['git_commit']}`",
        f"- Git dirty: `{report['git_dirty']}`",
        f"- Platform: `{report['platform']}`",
        f"- Bundle: `{report['bundle']}`",
        f"- Dashboard bytes on disk: `{report['bundle_size_bytes']:,}`",
        "",
        "Serialisation",
        f"- Compact JSON size: `{serial['json_size_bytes']:,}` bytes",
        f"- MessagePack size: `{serial['msgpack_size_bytes']:,}` bytes",
        f"- JSON encode: `{serial['json_encode_seconds']:.4f}s`",
        f"- MessagePack encode: `{serial['msgpack_encode_seconds']:.4f}s`",
        f"- JSON decode: `{serial['json_decode_seconds']:.4f}s`",
        f"- MessagePack decode: `{serial['msgpack_decode_seconds']:.4f}s`",
        "",
        "Transport",
        f"- Payload bytes: `{transport['payload_bytes']:,}`",
        f"- Workers: `{transport['workers']}`",
        f"- Tasks: `{transport['tasks']}`",
        f"- Pickle transport: `{transport['pickle_seconds']:.3f}s`",
        f"- Shared memory transport: `{transport['shared_memory_seconds']:.3f}s`",
        f"- Shared-memory speedup: `{transport['speedup_ratio']}`",
        f"- Checksums match: `{transport['checksums_match']}`",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(effective_argv)

    try:
        import msgpack
    except ImportError as exc:  # pragma: no cover - optional analysis dependency
        raise SystemExit(
            "msgpack is required for analysis/architecture_bakeoff.py. "
            "Install the analysis extras or run `python -m pip install msgpack`."
        ) from exc

    repo_root = Path(args.repo_root).resolve()
    bundle_path = Path(args.bundle).resolve() if args.bundle else _default_bundle(repo_root).resolve()
    output_root = Path(args.output_dir).resolve() if args.output_dir else _default_output_dir(repo_root)
    output_root.mkdir(parents=True, exist_ok=True)
    if any(output_root.iterdir()):
        raise ValueError(f"Architecture bake-off output directory must be empty: {output_root}")

    payload_text = bundle_path.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    payload_bytes = payload_text.encode("utf-8")

    json_encode_seconds, compact_json_bytes = _time_call(
        lambda: json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        args.repeats,
    )
    msgpack_encode_seconds, msgpack_bytes = _time_call(
        lambda: msgpack.packb(payload, use_bin_type=True),
        args.repeats,
    )
    json_decode_seconds, _ = _time_call(lambda: json.loads(compact_json_bytes.decode("utf-8")), args.repeats)
    msgpack_decode_seconds, _ = _time_call(lambda: msgpack.unpackb(msgpack_bytes, raw=False), args.repeats)
    transport = _transport_benchmark(compact_json_bytes, workers=max(1, int(args.workers)), tasks=max(1, int(args.tasks)))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "git_commit": _git_text(repo_root, "rev-parse", "HEAD"),
        "git_dirty": bool(_git_text(repo_root, "status", "--porcelain", "--untracked-files=no")),
        "platform": platform.platform(),
        "bundle": str(bundle_path),
        "bundle_size_bytes": len(payload_bytes),
        "command": {
            "argv": [sys.executable, str(Path(__file__).resolve()), *effective_argv],
            "display": subprocess.list2cmdline([sys.executable, str(Path(__file__).resolve()), *effective_argv]),
            "cwd": str(Path.cwd().resolve()),
        },
        "serialisation": {
            "json_size_bytes": len(compact_json_bytes),
            "msgpack_size_bytes": len(msgpack_bytes),
            "json_encode_seconds": round(json_encode_seconds, 6),
            "msgpack_encode_seconds": round(msgpack_encode_seconds, 6),
            "json_decode_seconds": round(json_decode_seconds, 6),
            "msgpack_decode_seconds": round(msgpack_decode_seconds, 6),
        },
        "transport": transport,
    }

    (output_root / "architecture_bakeoff.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown = _render_markdown(report)
    (output_root / "architecture_bakeoff.md").write_text(markdown, encoding="utf-8")

    print(f"Architecture bake-off: {output_root}")
    print(markdown)


if __name__ == "__main__":
    main()
