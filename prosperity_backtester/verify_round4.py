from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Mapping, Sequence

from .counterparty_research import run_round4_counterparty_research
from .dataset import load_round_dataset
from .experiments import TraderSpec, run_monte_carlo, run_replay
from .metadata import get_round_spec, products_for_round
from .platform import PerturbationConfig, generate_synthetic_market_days
from .provenance import capture_provenance


@dataclass
class CheckResult:
    name: str
    status: str
    detail: Dict[str, object] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "error": self.error,
        }


def _pass(name: str, **detail: object) -> CheckResult:
    return CheckResult(name=name, status="pass", detail=dict(detail))


def _fail(name: str, error: str, **detail: object) -> CheckResult:
    return CheckResult(name=name, status="fail", detail=dict(detail), error=error)


def validate_round4_data(data_dir: Path, days: Sequence[int]) -> CheckResult:
    try:
        dataset = load_round_dataset(data_dir, days, round_number=4)
    except Exception as exc:
        return _fail("data_validation", str(exc))
    expected = list(products_for_round(4))
    day_rows: List[Dict[str, object]] = []
    failures: List[str] = []
    for day in days:
        validation = dict(dataset[int(day)].validation)
        row = {
            "day": int(day),
            "price_rows": validation.get("price_rows"),
            "trade_rows": validation.get("trade_rows"),
            "timestamps": validation.get("timestamps"),
            "timestamp_min": validation.get("timestamp_min"),
            "timestamp_max": validation.get("timestamp_max"),
            "timestamp_step_ok": validation.get("timestamp_step_ok"),
            "products_seen": validation.get("products_seen"),
            "exact_product_match": validation.get("exact_product_match"),
            "duplicate_book_rows": validation.get("duplicate_book_rows"),
            "missing_products_count": len(validation.get("missing_products") or {}),
            "empty_book_rows": validation.get("empty_book_rows"),
            "one_sided_book_rows": validation.get("one_sided_book_rows"),
            "crossed_book_rows": validation.get("crossed_book_rows"),
            "trade_rows_unknown_symbol": validation.get("trade_rows_unknown_symbol"),
            "trade_rows_invalid_currency": validation.get("trade_rows_invalid_currency"),
            "trade_rows_invalid_quantity": validation.get("trade_rows_invalid_quantity"),
        }
        if row["price_rows"] != 120_000:
            failures.append(f"day {day}: expected 120000 price rows, got {row['price_rows']}")
        if row["timestamps"] != 10_000:
            failures.append(f"day {day}: expected 10000 timestamps, got {row['timestamps']}")
        if row["timestamp_min"] != 0 or row["timestamp_max"] != 999_900 or not row["timestamp_step_ok"]:
            failures.append(f"day {day}: timestamp range or step mismatch")
        if row["products_seen"] != expected or not row["exact_product_match"]:
            failures.append(f"day {day}: product set mismatch")
        for field_name in ("duplicate_book_rows", "missing_products_count", "crossed_book_rows", "trade_rows_unknown_symbol", "trade_rows_invalid_currency", "trade_rows_invalid_quantity"):
            if int(row[field_name] or 0) != 0:
                failures.append(f"day {day}: {field_name}={row[field_name]}")
        day_rows.append(row)
    manifest_path = data_dir / "manifest.json"
    if not manifest_path.is_file():
        failures.append("data/round4/manifest.json is missing")
    status = "pass" if not failures else "fail"
    return CheckResult(
        name="data_validation",
        status=status,
        detail={"days": day_rows, "manifest_exists": manifest_path.is_file()},
        error=None if status == "pass" else "; ".join(failures),
    )


def counterparty_presence_check(data_dir: Path, days: Sequence[int]) -> CheckResult:
    dataset = load_round_dataset(data_dir, days, round_number=4)
    names = set()
    trade_rows = 0
    for day_dataset in dataset.values():
        for by_product in day_dataset.trades_by_timestamp.values():
            for trades in by_product.values():
                for trade in trades:
                    trade_rows += 1
                    if trade.buyer:
                        names.add(str(trade.buyer))
                    if trade.seller:
                        names.add(str(trade.seller))
    if len(names) < 2:
        return _fail("counterparty_presence", "fewer than two named counterparties found", names=sorted(names), trade_rows=trade_rows)
    return _pass("counterparty_presence", names=sorted(names), counterparty_count=len(names), trade_rows=trade_rows)


def synthetic_round4_check(data_dir: Path, days: Sequence[int]) -> CheckResult:
    spec = get_round_spec(4)
    dataset = load_round_dataset(data_dir, days, round_number=4)
    historical_days = [dataset[day] for day in days]
    synthetic = generate_synthetic_market_days(
        days=(days[0],),
        seed=20260426,
        perturb=PerturbationConfig(synthetic_tick_limit=120, counterparty_edge_strength=0.25),
        round_spec=spec,
        historical_market_days=historical_days,
    )[0]
    products_match = set(synthetic.books_by_timestamp[synthetic.timestamps[0]]) == set(spec.products)
    names = {
        name
        for by_product in synthetic.trades_by_timestamp.values()
        for trades in by_product.values()
        for trade in trades
        for name in (trade.buyer, trade.seller)
        if name
    }
    if not products_match:
        return _fail("synthetic_round4", "synthetic products do not match Round 4 registry")
    if not names:
        return _fail("synthetic_round4", "synthetic named counterparty flow is absent")
    return _pass("synthetic_round4", tick_count=len(synthetic.timestamps), names=sorted(names)[:10])


def render_markdown(report: Mapping[str, object]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Round 4 Verification Report",
        "",
        f"- Generated at: `{report.get('generated_at')}`",
        f"- Data dir: `{report.get('data_dir')}`",
        f"- Output dir: `{report.get('output_dir')}`",
        f"- Overall status: **{summary.get('overall_status')}**",
        "",
        "| Check | Status | Error |",
        "| --- | --- | --- |",
    ]
    for check in report.get("checks", []):
        error = str(check.get("error") or "").replace("|", "\\|")
        lines.append(f"| `{check.get('name')}` | {check.get('status')} | {error} |")
    return "\n".join(lines).rstrip() + "\n"


def run_verify_round4(
    *,
    data_dir: Path,
    output_dir: Path,
    days: Sequence[int] = (1, 2, 3),
    trader_path: Path,
    skip_mc: bool = False,
    full: bool = False,
) -> Dict[str, object]:
    repo_root = Path(__file__).resolve().parent.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    checks: List[CheckResult] = []
    started = datetime.now(timezone.utc)

    checks.append(validate_round4_data(data_dir, days))
    checks.append(counterparty_presence_check(data_dir, days))
    try:
        research_summary = run_round4_counterparty_research(
            data_dir=data_dir,
            output_dir=output_dir / "counterparty_research",
            days=days,
        )
        checks.append(_pass("counterparty_research", **research_summary))
    except Exception as exc:
        checks.append(_fail("counterparty_research", str(exc)))

    noop_trader = repo_root / "examples" / "noop_round3_trader.py"
    try:
        replay = run_replay(
            trader_spec=TraderSpec(name="noop_round4", path=noop_trader),
            days=days,
            data_dir=data_dir,
            fill_model_name="base",
            perturbation=PerturbationConfig(),
            output_dir=output_dir / "replay_noop",
            run_name="r4_noop",
            round_number=4,
        )
        ok = replay.summary["final_pnl"] == 0 and replay.summary["fill_count"] == 0
        checks.append(_pass("replay_noop") if ok else _fail("replay_noop", "no-op replay produced fills or PnL", summary=replay.summary))
    except Exception as exc:
        checks.append(_fail("replay_noop", str(exc)))

    if trader_path.is_file():
        try:
            replay = run_replay(
                trader_spec=TraderSpec(name=trader_path.stem, path=trader_path),
                days=days,
                data_dir=data_dir,
                fill_model_name="base",
                perturbation=PerturbationConfig(),
                output_dir=output_dir / "replay_candidate",
                run_name="r4_candidate_replay",
                round_number=4,
            )
            checks.append(_pass("replay_candidate", final_pnl=replay.summary["final_pnl"], fill_count=replay.summary["fill_count"], per_product=replay.summary.get("per_product", {})))
        except Exception as exc:
            checks.append(_fail("replay_candidate", str(exc)))
    else:
        checks.append(CheckResult(name="replay_candidate", status="skip", error=f"trader not found: {trader_path}"))

    try:
        checks.append(synthetic_round4_check(data_dir, days))
    except Exception as exc:
        checks.append(_fail("synthetic_round4", str(exc)))

    if skip_mc or not trader_path.is_file():
        checks.append(CheckResult(name="mc_smoke", status="skip", error="skipped by request or missing trader"))
    else:
        sessions = 16 if full else 4
        try:
            a = run_monte_carlo(
                trader_spec=TraderSpec(name=trader_path.stem, path=trader_path),
                sessions=sessions,
                sample_sessions=min(2, sessions),
                days=(days[0],),
                data_dir=data_dir,
                fill_model_name="base",
                perturbation=PerturbationConfig(synthetic_tick_limit=160, counterparty_edge_strength=0.25),
                output_dir=output_dir / "mc_smoke_a",
                base_seed=20260426,
                run_name="r4_mc_smoke_a",
                round_number=4,
            )
            b = run_monte_carlo(
                trader_spec=TraderSpec(name=trader_path.stem, path=trader_path),
                sessions=sessions,
                sample_sessions=min(2, sessions),
                days=(days[0],),
                data_dir=data_dir,
                fill_model_name="base",
                perturbation=PerturbationConfig(synthetic_tick_limit=160, counterparty_edge_strength=0.25),
                output_dir=output_dir / "mc_smoke_b",
                base_seed=20260426,
                run_name="r4_mc_smoke_b",
                round_number=4,
            )
            pnl_a = [session.summary["final_pnl"] for session in a]
            pnl_b = [session.summary["final_pnl"] for session in b]
            if pnl_a != pnl_b:
                checks.append(_fail("mc_smoke", "identical seed MC runs differ", pnl_a=pnl_a, pnl_b=pnl_b))
            else:
                checks.append(_pass("mc_smoke", sessions=sessions, mean=sum(pnl_a) / len(pnl_a), min=min(pnl_a), max=max(pnl_a)))
        except Exception as exc:
            checks.append(_fail("mc_smoke", str(exc)))

    passed = sum(1 for check in checks if check.status == "pass")
    failed = sum(1 for check in checks if check.status == "fail")
    skipped = sum(1 for check in checks if check.status == "skip")
    report: Dict[str, object] = {
        "generated_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "data_dir": str(data_dir),
        "output_dir": str(output_dir),
        "days": [int(day) for day in days],
        "python_executable": sys.executable,
        "provenance": capture_provenance(start=repo_root),
        "summary": {
            "overall_status": "pass" if failed == 0 else "fail",
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        },
        "checks": [check.to_dict() for check in checks],
    }
    (output_dir / "verification_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (output_dir / "verification_report.md").write_text(render_markdown(report), encoding="utf-8")
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "type": "round4_verification",
                "created_at": started.isoformat(),
                "overall_status": report["summary"]["overall_status"],
                "report": "verification_report.json",
                "report_markdown": "verification_report.md",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return report
