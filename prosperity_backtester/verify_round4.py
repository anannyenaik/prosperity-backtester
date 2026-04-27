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
from .r4_manifest import build_round4_manifest
from .r4_mc_validation import run_round4_mc_validation


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


def _skip(name: str, reason: str, **detail: object) -> CheckResult:
    return CheckResult(name=name, status="skip", detail=dict(detail), error=reason)


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _fill_channel_summary(fills: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    channels: Dict[str, Dict[str, object]] = {}
    for fill in fills:
        channel = str(fill.get("kind") or "unknown")
        bucket = channels.setdefault(channel, {"fill_count": 0, "quantity": 0, "notional": 0.0, "per_product": {}})
        qty = abs(int(fill.get("quantity") or 0))
        bucket["fill_count"] = int(bucket["fill_count"]) + 1
        bucket["quantity"] = int(bucket["quantity"]) + qty
        bucket["notional"] = float(bucket["notional"]) + qty * float(fill.get("price") or 0.0)
        product = str(fill.get("product") or "")
        per_product = bucket["per_product"]
        per_product[product] = int(per_product.get(product, 0)) + 1
    return channels


def _replay_summary_payload(replay) -> Dict[str, object]:
    return {
        "final_pnl": replay.summary.get("final_pnl"),
        "fill_count": replay.summary.get("fill_count"),
        "order_count": replay.summary.get("order_count"),
        "limit_breaches": replay.summary.get("limit_breaches"),
        "max_drawdown": replay.summary.get("max_drawdown"),
        "final_positions": replay.summary.get("final_positions"),
        "per_product": replay.summary.get("per_product"),
        "fill_channels": _fill_channel_summary(replay.fills),
        "candidate_promoted": False,
    }


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
        for field_name in ("negative_price_levels", "zero_or_negative_mid_rows"):
            if int(validation.get(field_name) or 0) != 0:
                failures.append(f"day {day}: {field_name}={validation.get(field_name)}")
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
    final_decision = report.get("final_decision") or {}
    lines = [
        "# Round 4 Verification Report",
        "",
        f"- Generated at: `{report.get('generated_at')}`",
        f"- Data dir: `{report.get('data_dir')}`",
        f"- Output dir: `{report.get('output_dir')}`",
        f"- Overall status: **{summary.get('overall_status')}**",
        f"- Backtester decision-grade: **{final_decision.get('backtester_decision_grade')}**",
        f"- Candidate promoted: **{final_decision.get('candidate_promoted')}**",
        "",
        "| Check | Status | Error |",
        "| --- | --- | --- |",
    ]
    for check in report.get("checks", []):
        error = str(check.get("error") or "").replace("|", "\\|")
        lines.append(f"| `{check.get('name')}` | {check.get('status')} | {error} |")
    limitations = report.get("known_limitations") or []
    if limitations:
        lines.extend(["", "## Known Limitations", ""])
        for item in limitations:
            lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def run_verify_round4(
    *,
    data_dir: Path,
    output_dir: Path,
    days: Sequence[int] = (1, 2, 3),
    trader_path: Path,
    skip_mc: bool = False,
    full: bool = False,
    fast: bool = False,
    strict: bool = False,
) -> Dict[str, object]:
    repo_root = Path(__file__).resolve().parent.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    checks: List[CheckResult] = []
    started = datetime.now(timezone.utc)
    mode = "full" if full else "fast"
    replay_days = tuple(days if full else (days[0],))
    replay_tick_limit = None if full else 1200

    try:
        manifest = build_round4_manifest(data_dir=data_dir, output_dir=output_dir / "manifest", days=days)
        checks.append(_pass("r4_manifest", status=manifest.get("status"), data_hash=manifest.get("data_hash"), artefact="manifest/manifest_report.json") if manifest.get("status") == "pass" else _fail("r4_manifest", "manifest reported issues", artefact="manifest/manifest_report.json", issues=manifest.get("issues")))
    except Exception as exc:
        checks.append(_fail("r4_manifest", str(exc)))

    checks.append(validate_round4_data(data_dir, days))
    checks.append(counterparty_presence_check(data_dir, days))
    checks.append(_skip("test_summary", "pytest is not run inside verify-round4; run the recorded pytest commands as the verification gate"))
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
            days=replay_days,
            data_dir=data_dir,
            fill_model_name="base",
            perturbation=PerturbationConfig(),
            output_dir=output_dir / "replay_noop",
            run_name="r4_noop",
            round_number=4,
            write_bundle=False,
            historical_tick_limit=replay_tick_limit,
        )
        ok = replay.summary["final_pnl"] == 0 and replay.summary["fill_count"] == 0
        replay_payload = _replay_summary_payload(replay)
        replay_payload["days"] = list(replay_days)
        replay_payload["historical_tick_limit"] = replay_tick_limit
        _write_json(output_dir / "replay_noop_summary.json", replay_payload)
        checks.append(_pass("replay_noop", artefact="replay_noop_summary.json", **replay_payload) if ok else _fail("replay_noop", "no-op replay produced fills or PnL", artefact="replay_noop_summary.json", summary=replay_payload))
    except Exception as exc:
        checks.append(_fail("replay_noop", str(exc)))

    candidate_replay_payload: Dict[str, object] | None = None
    if trader_path.is_file():
        try:
            replay = run_replay(
                trader_spec=TraderSpec(name=trader_path.stem, path=trader_path),
                days=replay_days,
                data_dir=data_dir,
                fill_model_name="base",
                perturbation=PerturbationConfig(),
                output_dir=output_dir / "replay_candidate",
                run_name="r4_candidate_replay",
                round_number=4,
                write_bundle=False,
                historical_tick_limit=replay_tick_limit,
            )
            candidate_replay_payload = _replay_summary_payload(replay)
            candidate_replay_payload["days"] = list(replay_days)
            candidate_replay_payload["historical_tick_limit"] = replay_tick_limit
            _write_json(output_dir / "replay_candidate_summary.json", candidate_replay_payload)
            checks.append(_pass("replay_candidate", artefact="replay_candidate_summary.json", **candidate_replay_payload))
        except Exception as exc:
            checks.append(_fail("replay_candidate", str(exc)))
    else:
        checks.append(_skip("replay_candidate", f"trader not found: {trader_path}"))

    if trader_path.is_file():
        ablation_rows: List[Dict[str, object]] = []
        ablation_specs = [
            ("no_names", "base", PerturbationConfig(), {"CONFIG.use_counterparties": False}),
            ("fill_none", "base", PerturbationConfig(trade_matching_mode="none"), None),
            ("fill_worse", "base", PerturbationConfig(trade_matching_mode="worse"), None),
        ]
        if full:
            ablation_specs.extend(
                [
                    ("fill_all", "base", PerturbationConfig(trade_matching_mode="all"), None),
                    ("adverse", "low_fill_quality", PerturbationConfig(passive_fill_scale=0.7, missed_fill_additive=0.08, adverse_selection_ticks=1), None),
                    ("harsh_adverse", "low_fill_quality", PerturbationConfig(passive_fill_scale=0.5, missed_fill_additive=0.15, adverse_selection_ticks=2, slippage_multiplier=1.5), None),
                    ("hydrogel_shift_down", "base", PerturbationConfig(shock_tick=50, hydrogel_shock=-60.0), None),
                    ("hydrogel_shift_up", "base", PerturbationConfig(shock_tick=50, hydrogel_shock=60.0), None),
                ]
            )
        ablation_days = replay_days
        try:
            for name, fill_model_name, perturbation, overrides in ablation_specs:
                try:
                    replay = run_replay(
                        trader_spec=TraderSpec(name=name, path=trader_path, overrides=overrides),
                        days=ablation_days,
                        data_dir=data_dir,
                        fill_model_name=fill_model_name,
                        perturbation=perturbation,
                        output_dir=output_dir / "ablations" / name,
                        run_name=f"r4_ablation_{name}",
                        round_number=4,
                        write_bundle=False,
                        historical_tick_limit=replay_tick_limit,
                    )
                    ablation_rows.append(
                        {
                            "name": name,
                            "status": "pass",
                            "days": list(ablation_days),
                            "historical_tick_limit": replay_tick_limit,
                            "fill_model": fill_model_name,
                            "perturbation": perturbation.to_dict(),
                            "final_pnl": replay.summary.get("final_pnl"),
                            "fill_count": replay.summary.get("fill_count"),
                            "limit_breaches": replay.summary.get("limit_breaches"),
                            "fill_channels": _fill_channel_summary(replay.fills),
                        }
                    )
                except Exception as exc:
                    row_status = "skip" if overrides else "fail"
                    ablation_rows.append(
                        {
                            "name": name,
                            "status": row_status,
                            "days": list(ablation_days),
                            "historical_tick_limit": replay_tick_limit,
                            "fill_model": fill_model_name,
                            "perturbation": perturbation.to_dict(),
                            "error": str(exc),
                        }
                    )
            _write_json(output_dir / "ablation_summary.json", {"rows": ablation_rows, "candidate_promoted": False})
            failed_ablation_rows = [row for row in ablation_rows if row.get("status") == "fail"]
            if failed_ablation_rows:
                checks.append(_fail("ablation", "one or more ablation rows failed", row_count=len(ablation_rows), artefact="ablation_summary.json"))
            else:
                checks.append(_pass("ablation", row_count=len(ablation_rows), artefact="ablation_summary.json"))
        except Exception as exc:
            _write_json(output_dir / "ablation_summary.json", {"rows": ablation_rows, "error": str(exc), "candidate_promoted": False})
            checks.append(_fail("ablation", str(exc), completed_rows=len(ablation_rows), artefact="ablation_summary.json"))
    else:
        checks.append(_skip("ablation", "missing trader"))

    try:
        checks.append(synthetic_round4_check(data_dir, days))
    except Exception as exc:
        checks.append(_fail("synthetic_round4", str(exc)))

    mc_validation_status = "skip"
    if skip_mc:
        checks.append(_skip("mc_validation", "skipped by request"))
        checks.append(_skip("mc_smoke", "skipped by request"))
    elif not trader_path.is_file():
        checks.append(_skip("mc_validation", "missing trader"))
        checks.append(_skip("mc_smoke", "missing trader"))
    else:
        try:
            mc_validation = run_round4_mc_validation(
                data_dir=data_dir,
                output_dir=output_dir / "mc_validation",
                days=days,
                preset="full" if full else "fast",
            )
            mc_validation_status = str(mc_validation.get("status"))
            status = mc_validation_status
            if status == "fail":
                checks.append(_fail("mc_validation", "MC validation failed", artefact="mc_validation/mc_validation_report.json"))
            elif status == "warn":
                checks.append(CheckResult(name="mc_validation", status="warn", detail={"artefact": "mc_validation/mc_validation_report.json"}, error="MC validation has resemblance warnings"))
            else:
                checks.append(_pass("mc_validation", artefact="mc_validation/mc_validation_report.json"))
        except Exception as exc:
            checks.append(_fail("mc_validation", str(exc)))
        sessions = 8 if full else 2
        try:
            a = run_monte_carlo(
                trader_spec=TraderSpec(name=trader_path.stem, path=trader_path),
                sessions=sessions,
                sample_sessions=min(2, sessions),
                days=(days[0],),
                data_dir=data_dir,
                fill_model_name="base",
                perturbation=PerturbationConfig(synthetic_tick_limit=300 if full else 120, counterparty_edge_strength=0.25),
                output_dir=output_dir / "mc_smoke_a",
                base_seed=20260426,
                run_name="r4_mc_smoke_a",
                round_number=4,
                monte_carlo_backend="classic",
                write_bundle=False,
            )
            b = run_monte_carlo(
                trader_spec=TraderSpec(name=trader_path.stem, path=trader_path),
                sessions=sessions,
                sample_sessions=min(2, sessions),
                days=(days[0],),
                data_dir=data_dir,
                fill_model_name="base",
                perturbation=PerturbationConfig(synthetic_tick_limit=300 if full else 120, counterparty_edge_strength=0.25),
                output_dir=output_dir / "mc_smoke_b",
                base_seed=20260426,
                run_name="r4_mc_smoke_b",
                round_number=4,
                monte_carlo_backend="classic",
                write_bundle=False,
            )
            pnl_a = [session.summary["final_pnl"] for session in a]
            pnl_b = [session.summary["final_pnl"] for session in b]
            _write_json(output_dir / "mc_smoke_summary.json", {"pnl_a": pnl_a, "pnl_b": pnl_b, "sessions": sessions})
            if pnl_a != pnl_b:
                checks.append(_fail("mc_smoke", "identical seed MC runs differ", pnl_a=pnl_a, pnl_b=pnl_b))
            else:
                checks.append(_pass("mc_smoke", sessions=sessions, mean=sum(pnl_a) / len(pnl_a), min=min(pnl_a), max=max(pnl_a), artefact="mc_smoke_summary.json"))
        except Exception as exc:
            checks.append(_fail("mc_smoke", str(exc)))

    passed = sum(1 for check in checks if check.status == "pass")
    failed = sum(1 for check in checks if check.status == "fail")
    skipped = sum(1 for check in checks if check.status == "skip")
    warnings = sum(1 for check in checks if check.status == "warn")
    decision_grade_blockers: List[str] = []
    if failed:
        decision_grade_blockers.append("one or more verification checks failed")
    if skipped:
        decision_grade_blockers.append("one or more verification checks were skipped")
    if warnings:
        decision_grade_blockers.append("one or more verification checks produced warnings")
    if skip_mc:
        decision_grade_blockers.append("MC validation was skipped")
    if mc_validation_status != "pass":
        decision_grade_blockers.append("MC validation did not pass cleanly")
    decision_grade = not decision_grade_blockers
    known_limitations = [
        "Passive fills are inferred from trade price versus contemporaneous visible book; hidden queue priority is not observable.",
        "Counterparty names are metadata and are not treated as aggressor-side proof.",
        "MC validation checks reproducibility and resemblance, but cannot prove equivalence to the official simulator.",
        "No trading strategy is promoted by this harness.",
    ]
    report: Dict[str, object] = {
        "generated_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "data_dir": str(data_dir),
        "output_dir": str(output_dir),
        "days": [int(day) for day in days],
        "mode": mode,
        "replay_scope": {
            "days": [int(day) for day in replay_days],
            "historical_tick_limit": replay_tick_limit,
            "truncated": replay_tick_limit is not None,
        },
        "strict": bool(strict),
        "python_executable": sys.executable,
        "provenance": capture_provenance(start=repo_root),
        "summary": {
            "overall_status": "pass" if failed == 0 else "fail",
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "warnings": warnings,
        },
        "checks": [check.to_dict() for check in checks],
        "replay_summary": candidate_replay_payload,
        "known_limitations": known_limitations,
        "final_decision": {
            "backtester_decision_grade": decision_grade,
            "decision_grade_blockers": decision_grade_blockers,
            "candidate_promoted": False,
            "strategy_promotion_decision": "no",
        },
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
