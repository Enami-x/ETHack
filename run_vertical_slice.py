"""
run_vertical_slice.py
=====================
Vertical slice runner — proves end-to-end pipeline wiring with zero external dependencies.

Execution order:
  Stage 1  →  raw_signals        (load fixture)
  Stage 2  →  processed_signals  (normalize — in-memory only, no table)
  Stage 3  →  risk_scores
  Stage 4  →  scenarios
  Stage 5  →  procurement_recs
  Stage 6  →  reserve_plans
  Stage 7  →  reports

All state is held in a single in-memory dict `STATE` that mimics the Supabase table structure.
No network calls, no DB connections, no LLM calls.

Usage:
    python run_vertical_slice.py
"""

import json
import sys
import time

# ── Stage agents ──────────────────────────────────────────────────────────────
from agents.stage1_collector.agent import load_mock_signal
from agents.stage2_processor.agent import process_signal
from agents.stage3_risk.agent import score_risk
from agents.stage4_scenario.agent import model_scenario
from agents.stage5_procurement.agent import recommend_procurement
from agents.stage6_reserves.agent import optimize_reserves
from agents.stage7_reporting.agent import compile_report


# ── In-memory shared state (mirrors Supabase tables) ─────────────────────────
STATE: dict = {
    "raw_signals": [],
    "processed_signals": [],   # in-memory only — no Supabase table in slice
    "risk_scores": [],
    "scenarios": [],
    "procurement_recs": [],
    "reserve_plans": [],
    "reports": [],
}


def _print_section(title: str) -> None:
    bar = "-" * 72
    print(f"\n{bar}")
    print(f"  {title}")
    print(bar)


def _dump(label: str, obj: dict) -> None:
    print(f"\n-- {label} --")
    print(json.dumps(obj, indent=2, default=str))


def run_pipeline() -> dict:
    """Execute all 7 stages sequentially; return final STATE dict."""

    start = time.perf_counter()

    # ── Stage 1: Data Collection ──────────────────────────────────────────────
    _print_section("STAGE 1 — Data Collection (load mock fixture)")
    raw_signal = load_mock_signal()
    STATE["raw_signals"].append(raw_signal)
    _dump("raw_signal", raw_signal)

    # ── Stage 2: Data Processing ──────────────────────────────────────────────
    _print_section("STAGE 2 — Data Processing (normalize raw signal)")
    processed = process_signal(raw_signal)
    STATE["processed_signals"].append(processed)
    _dump("processed_signal", processed)

    # ── Stage 3: Risk Intelligence ────────────────────────────────────────────
    _print_section("STAGE 3 — Risk Intelligence Agent (score risk)")
    risk_score = score_risk(processed)
    STATE["risk_scores"].append(risk_score)
    _dump("risk_score", risk_score)

    # ── Stage 4: Scenario Modeling ────────────────────────────────────────────
    _print_section("STAGE 4 — Scenario Modeling Agent (hormuz_partial_closure)")
    scenario = model_scenario(risk_score)
    STATE["scenarios"].append(scenario)
    _dump("scenario", scenario)

    # ── Stage 5: Procurement ──────────────────────────────────────────────────
    _print_section("STAGE 5 — Procurement Agent (rank alternatives)")
    proc_rec = recommend_procurement(scenario)
    STATE["procurement_recs"].append(proc_rec)
    _dump("procurement_rec", proc_rec)

    # ── Stage 6: Reserve Optimization ────────────────────────────────────────
    _print_section("STAGE 6 — Reserve Optimization Agent (SPR drawdown)")
    reserve_plan = optimize_reserves(scenario)
    STATE["reserve_plans"].append(reserve_plan)
    _dump("reserve_plan", reserve_plan)

    # ── Stage 7: Reporting ────────────────────────────────────────────────────
    _print_section("STAGE 7 — Reporting Agent (compile markdown report)")
    report = compile_report(risk_score, scenario, proc_rec, reserve_plan)
    STATE["reports"].append(report)
    _dump("report (header only - body_markdown truncated)", {
        k: v if k != "body_markdown" else f"<{len(v)} chars - see full output below>"
        for k, v in report.items()
    })
    print("\n-- report.body_markdown --")
    print(report["body_markdown"])

    elapsed = time.perf_counter() - start

    # -- Final State Summary ---------------------------------------------------
    _print_section("FINAL STATE - All 6 tables (processed_signals in-memory only)")
    for table, rows in STATE.items():
        count = len(rows)
        print(f"\n  [{table}]  {count} row(s)")
        for row in rows:
            # Truncate body_markdown in summary
            summary = {
                k: (v if k != "body_markdown" else "<truncated>")
                for k, v in row.items()
            }
            print("   ", json.dumps(summary, default=str))

    print(f"\n[OK] Pipeline completed in {elapsed*1000:.1f} ms")

    return STATE


if __name__ == "__main__":
    try:
        run_pipeline()
    except Exception as exc:
        print(f"\n[ERROR] Pipeline failed: {exc}", file=sys.stderr)
        raise
