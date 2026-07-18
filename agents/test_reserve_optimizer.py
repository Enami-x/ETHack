"""
/agents/test_reserve_optimizer.py
===================================
CLI test harness for Stage 6 — Reserve Optimization Agent.

What it does:
  1. Fetches hormuz_partial_closure severity=0.9 from Supabase (consistent with Stage 5)
  2. Runs optimize_reserves() — prints full drawdown schedule table + policy text
  3. Fetches red_sea_suspension severity=0.3 from Supabase (low-severity test case)
  4. Runs optimize_reserves() on that — confirms policy_recommendation is NOT CRITICAL
  5. Sanity checks for BOTH runs:
       - draw_pct values sum to ~1.0 (within floating-point tolerance)
       - schedule is front-loaded (first-third avg > last-third avg)
  6. Validates both against §5 Stage 6 schema
  7. Writes both to reserve_plans Supabase table, reads back to confirm round-trip

Usage (from repo root):
    python -m agents.test_reserve_optimizer

Requires: .env with SUPABASE_URL and SUPABASE_SERVICE_KEY
"""

import json
import logging
import sys
import pathlib
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

try:
    from agents.reserve_optimizer import (
        optimize_reserves,
        SPR_DAYS_CRITICAL, SPR_DAYS_CAUTION,
        PHASE_WEIGHT_HIGH, PHASE_WEIGHT_MED, PHASE_WEIGHT_LOW,
        REPLENISHMENT_OVERHEAD_FACTOR,
    )
    from db.supabase_client import supabase
except ModuleNotFoundError:
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from agents.reserve_optimizer import (
        optimize_reserves,
        SPR_DAYS_CRITICAL, SPR_DAYS_CAUTION,
        PHASE_WEIGHT_HIGH, PHASE_WEIGHT_MED, PHASE_WEIGHT_LOW,
        REPLENISHMENT_OVERHEAD_FACTOR,
    )
    from db.supabase_client import supabase


# ---------------------------------------------------------------------------
# §5 Stage 6 schema — field-by-field validator
# ---------------------------------------------------------------------------
REQUIRED_FIELDS: dict[str, type | tuple] = {
    "id":                                 str,
    "scenario_id":                        (str, type(None)),
    "drawdown_schedule":                  list,
    "days_of_cover_remaining":            float,
    "replenishment_window_estimate_days": float,
    "policy_recommendation":              str,
    "generated_at":                       str,
}


def _iso8601(v: str) -> bool:
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return True
    except (ValueError, AttributeError):
        return False


def validate_reserve_plan(row: dict, label: str) -> list[str]:
    errors: list[str] = []
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in row:
            errors.append(f"[{label}] MISSING field: '{field}'")
        elif not isinstance(row[field], expected_type):
            errors.append(
                f"[{label}] '{field}': expected {expected_type}, "
                f"got {type(row[field]).__name__}"
            )
    if "drawdown_schedule" in row:
        sched = row["drawdown_schedule"]
        if not all(isinstance(e, dict) and "day" in e and "draw_pct" in e for e in sched):
            errors.append(
                f"[{label}] drawdown_schedule entries must be dicts with 'day' and 'draw_pct'."
            )
    if "days_of_cover_remaining" in row and row["days_of_cover_remaining"] < 0:
        errors.append(f"[{label}] days_of_cover_remaining is negative.")
    if "replenishment_window_estimate_days" in row and row["replenishment_window_estimate_days"] < 0:
        errors.append(f"[{label}] replenishment_window_estimate_days is negative.")
    if "generated_at" in row and not _iso8601(row["generated_at"]):
        errors.append(f"[{label}] generated_at not valid ISO8601: {row['generated_at']!r}")
    return errors


def _sep(char: str = "-", width: int = 70) -> str:
    return char * width


def _fetch_scenario(scenario_type: str, severity: float) -> dict:
    """Fetch the most recent matching scenario from Supabase."""
    try:
        resp = (
            supabase.table("scenarios")
            .select("*")
            .eq("scenario_type", scenario_type)
            .eq("severity", severity)
            .order("generated_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = resp.data
    except Exception as exc:
        print(f"  [ERROR] Supabase read failed for {scenario_type}@{severity}: {exc}")
        sys.exit(1)
    if not rows:
        print(f"  [ERROR] No '{scenario_type}' scenario at severity={severity} in Supabase.")
        print("  Run 'python -m agents.test_scenario_modeling' first.")
        sys.exit(1)
    return rows[0]


def _run_and_print(scenario: dict, label: str, all_errors: list, all_results: list) -> dict | None:
    """Run optimize_reserves, print schedule + policy, validate. Returns result or None."""
    stype    = scenario["scenario_type"]
    sev      = scenario["severity"]
    s_id     = scenario["id"]
    days_rem = scenario["spr_days_remaining_estimate"]

    print(_sep("="))
    print(f"  TEST CASE: {label}")
    print(_sep("="))
    print(f"    scenario_type            : {stype}")
    print(f"    severity                 : {sev}")
    print(f"    supply_gap_pct           : {scenario['supply_gap_pct']}")
    print(f"    spr_days_remaining (S4)  : {days_rem}")
    print()

    try:
        result = optimize_reserves(scenario)
    except Exception as exc:
        msg = f"[{label}] optimize_reserves() raised: {exc}"
        print(f"  [ERROR] {msg}")
        all_errors.append(msg)
        return None

    # -----------------------------------------------------------------------
    # Print drawdown schedule table
    # -----------------------------------------------------------------------
    sched = result["drawdown_schedule"]
    total_days = len(sched)
    p1_end = total_days // 3
    p2_end = (2 * total_days) // 3

    print(f"  DRAWDOWN SCHEDULE ({total_days} days)")
    print(f"  {'Day':>4}  {'draw_pct':>9}  {'Cumulative':>10}  Phase")
    print("  " + "-" * 40)
    cumulative = 0.0
    for entry in sched:
        d   = entry["day"]
        dp  = entry["draw_pct"]
        cumulative = round(cumulative + dp, 6)
        if d <= p1_end:
            phase = "1 (CRISIS — full SPR load)"
        elif d <= p2_end:
            phase = "2 (PARTIAL procurement)"
        else:
            phase = "3 (TAPER — procurement online)"
        print(f"  {d:>4}  {dp:>9.6f}  {cumulative:>10.6f}  {phase}")

    print()
    print(f"  days_of_cover_remaining          : {result['days_of_cover_remaining']}")
    print(f"  replenishment_window_estimate_days: {result['replenishment_window_estimate_days']}")
    print()
    print(f"  POLICY RECOMMENDATION:")
    # Word-wrap at 76 chars
    words, line = [], ""
    for word in result["policy_recommendation"].split():
        if len(line) + len(word) + 1 > 76:
            print(f"    {line}")
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        print(f"    {line}")
    print()

    # -----------------------------------------------------------------------
    # SANITY CHECK 1: draw_pct sums to ~1.0
    # -----------------------------------------------------------------------
    print(_sep("-"))
    print(f"  SANITY CHECK 1 — draw_pct sums to ~1.0 [{label}]")
    total_draw = sum(e["draw_pct"] for e in sched)
    tolerance  = 1e-4
    if abs(total_draw - 1.0) <= tolerance:
        print(f"  [PASS] SUM(draw_pct) = {total_draw:.8f} ≈ 1.0 (within {tolerance})")
    else:
        msg = f"[FAIL] SUM(draw_pct) = {total_draw:.8f} — expected 1.0 ± {tolerance}"
        print(f"  {msg}")
        all_errors.append(f"[{label}] {msg}")

    # -----------------------------------------------------------------------
    # SANITY CHECK 2: front-loaded (first-third avg > last-third avg)
    # -----------------------------------------------------------------------
    print()
    print(f"  SANITY CHECK 2 — schedule is front-loaded [{label}]")
    first_third = [e["draw_pct"] for e in sched[:p1_end]] or [0.0]
    last_third  = [e["draw_pct"] for e in sched[p2_end:]] or [0.0]
    avg_first   = sum(first_third) / len(first_third)
    avg_last    = sum(last_third)  / len(last_third)
    print(f"    avg draw_pct first-third (days 1–{p1_end})     : {avg_first:.6f}")
    print(f"    avg draw_pct last-third  (days {p2_end+1}–{total_days}): {avg_last:.6f}")
    if avg_first > avg_last:
        print(f"  [PASS] Schedule is front-loaded ({avg_first:.6f} > {avg_last:.6f})")
    else:
        msg = (
            f"[FAIL] Schedule is NOT front-loaded — "
            f"first-third avg {avg_first:.6f} <= last-third avg {avg_last:.6f}"
        )
        print(f"  {msg}")
        all_errors.append(f"[{label}] {msg}")

    # -----------------------------------------------------------------------
    # SANITY CHECK 3 (low-severity only): policy must NOT say CRITICAL
    # -----------------------------------------------------------------------
    if "low" in label.lower() or sev <= 0.3:
        print()
        print(f"  SANITY CHECK 3 — low-severity policy must NOT be CRITICAL [{label}]")
        if "[CRITICAL]" in result["policy_recommendation"]:
            msg = (
                f"[FAIL] Low-severity scenario ({sev}) produced a CRITICAL policy — "
                f"threshold logic is broken."
            )
            print(f"  {msg}")
            all_errors.append(f"[{label}] {msg}")
        else:
            # Extract the label from the recommendation
            rec = result["policy_recommendation"]
            status = rec[1:rec.index("]")] if "[" in rec and "]" in rec else "UNKNOWN"
            print(f"  [PASS] Policy status is [{status}] — not CRITICAL for severity={sev}.")

    print()
    all_results.append(result)
    return result


def main() -> None:
    print(_sep("="))
    print("  Stage 6 — Reserve Optimization Agent: Test Harness")
    print(_sep("="))
    print(f"  Run at: {datetime.now(timezone.utc).isoformat()}")
    print(f"  Phase weights: HIGH={PHASE_WEIGHT_HIGH}, MED={PHASE_WEIGHT_MED}, LOW={PHASE_WEIGHT_LOW}")
    print(f"  Thresholds   : CRITICAL<{SPR_DAYS_CRITICAL}d | CAUTION {SPR_DAYS_CRITICAL}–{SPR_DAYS_CAUTION}d | STABLE>{SPR_DAYS_CAUTION}d")
    print(f"  Replenishment overhead: {REPLENISHMENT_OVERHEAD_FACTOR}×\n")

    all_errors:  list[str]  = []
    all_results: list[dict] = []

    # -----------------------------------------------------------------------
    # TEST CASE 1: hormuz_partial_closure @ severity=0.9 (HIGH severity)
    # -----------------------------------------------------------------------
    scenario_high = _fetch_scenario("hormuz_partial_closure", 0.9)
    _run_and_print(scenario_high, "HORMUZ severity=0.9 (HIGH)", all_errors, all_results)

    # -----------------------------------------------------------------------
    # TEST CASE 2: red_sea_suspension @ severity=0.3 (LOW severity)
    # -----------------------------------------------------------------------
    scenario_low = _fetch_scenario("red_sea_suspension", 0.3)
    _run_and_print(scenario_low, "RED_SEA severity=0.3 (LOW)", all_errors, all_results)

    # -----------------------------------------------------------------------
    # Schema validation
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  Schema validation (§5 Stage 6)")
    print(_sep("-"))
    for result in all_results:
        label = f"{result['scenario_id']}"
        errs  = validate_reserve_plan(result, label)
        all_errors.extend(errs)
    if all_errors:
        for e in all_errors:
            print(f"  [FAIL] {e}")
        print("\n[ABORTING] Validation errors — not writing to Supabase.")
        sys.exit(1)
    else:
        print(f"  [PASS] All {len(all_results)} reserve plans passed §5 Stage 6 schema validation.\n")

    # -----------------------------------------------------------------------
    # Write to Supabase reserve_plans
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  Writing to Supabase: reserve_plans")
    print(_sep("-"))

    insert_rows = []
    for result in all_results:
        insert_rows.append({
            "scenario_id":                        result["scenario_id"],
            "drawdown_schedule":                  result["drawdown_schedule"],
            "days_of_cover_remaining":            result["days_of_cover_remaining"],
            "replenishment_window_estimate_days": result["replenishment_window_estimate_days"],
            "policy_recommendation":              result["policy_recommendation"],
            "generated_at":                       result["generated_at"],
        })

    try:
        supabase.table("reserve_plans").insert(insert_rows).execute()
        written = len(insert_rows)
        print(f"  Wrote {written} reserve_plan row(s) to Supabase.\n")
    except Exception as exc:
        print(f"  [ERROR] Supabase write failed: {exc}")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Read back to confirm round-trip
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  Reading back from Supabase (round-trip check)")
    print(_sep("-"))
    try:
        read_resp = (
            supabase.table("reserve_plans")
            .select("scenario_id, days_of_cover_remaining, replenishment_window_estimate_days, generated_at")
            .order("generated_at", desc=True)
            .limit(written + 2)
            .execute()
        )
        read_back = read_resp.data
    except Exception as exc:
        print(f"  [ERROR] Supabase read-back failed: {exc}")
        sys.exit(1)

    print(f"  Read back {len(read_back)} row(s) from reserve_plans.\n")
    for rb in read_back[:2]:
        print(f"    scenario_id    : {rb.get('scenario_id')}")
        print(f"    days_remaining : {rb.get('days_of_cover_remaining')}")
        print(f"    replenishment  : {rb.get('replenishment_window_estimate_days')} days")
        print(f"    generated_at   : {rb.get('generated_at')}")
        print()

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  SUMMARY")
    print(_sep("="))
    print(f"  Test cases run          : {len(all_results)}")
    print(f"  Schema errors           : {len(all_errors)}")
    print(f"  Sanity: sum≈1.0         : PASS (both cases)")
    print(f"  Sanity: front-loaded    : PASS (both cases)")
    print(f"  Sanity: low-sev ≠ CRIT  : PASS (red_sea 0.3 = STABLE/CAUTION)")
    print(f"  Wrote to Supabase       : {written}")
    print(f"  Read back               : {len(read_back)}")
    print()
    print("  [PASS] Stage 6 Reserve Optimizer: all checks, write, and round-trip complete.")
    print()


if __name__ == "__main__":
    main()
