"""
/agents/test_scenario_modeling.py
==================================
CLI test harness for Stage 4 — Scenario Modeling Agent.

What it does:
  1. Runs all 3 scenario types at severity = 0.3, 0.6, 0.9 (9 total runs)
  2. Prints a formatted results table for all 9 runs
  3. Prints the full assumptions list for each run
  4. Validates each output against the §5 Stage 4 schema
  5. Sanity check: supply_gap_pct increases monotonically with severity per scenario
  6. Writes all 9 results to the `scenarios` Supabase table
  7. Reads back from Supabase to confirm round-trip
  8. Exits with code 1 if ANY validation or sanity check fails

Usage (from repo root):
    python -m agents.test_scenario_modeling
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
    from agents.scenario_modeling import run_scenario, VALID_SCENARIO_TYPES
    from db.supabase_client import supabase
except ModuleNotFoundError:
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from agents.scenario_modeling import run_scenario, VALID_SCENARIO_TYPES
    from db.supabase_client import supabase


# ---------------------------------------------------------------------------
# §5 Stage 4 schema — validation
# ---------------------------------------------------------------------------
REQUIRED_FIELDS: dict[str, type] = {
    "id":                               str,
    "scenario_type":                    str,
    "severity":                         float,
    "supply_gap_pct":                   float,
    "price_impact_pct":                 float,
    "refinery_utilization_impact_pct":  float,
    "spr_days_remaining_estimate":      float,
    "assumptions":                      list,
    "generated_at":                     str,
}

VALID_SCENARIOS = VALID_SCENARIO_TYPES


def _iso8601(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except (ValueError, AttributeError):
        return False


def validate_scenario_row(row: dict, label: str) -> list[str]:
    errors: list[str] = []
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in row:
            errors.append(f"[{label}] MISSING field: '{field}'")
        elif not isinstance(row[field], expected_type):
            errors.append(
                f"[{label}] '{field}': expected {expected_type.__name__}, "
                f"got {type(row[field]).__name__}"
            )

    for float_field in ("severity", "supply_gap_pct", "price_impact_pct",
                        "refinery_utilization_impact_pct", "spr_days_remaining_estimate"):
        if float_field in row:
            v = row[float_field]
            if v < 0.0:
                errors.append(f"[{label}] '{float_field}' is negative: {v}")

    if "supply_gap_pct" in row and row.get("supply_gap_pct", 0) > 1.0:
        errors.append(f"[{label}] 'supply_gap_pct' > 1.0: {row['supply_gap_pct']}")

    if "scenario_type" in row and row["scenario_type"] not in VALID_SCENARIOS:
        errors.append(f"[{label}] 'scenario_type' invalid: '{row['scenario_type']}'")

    if "assumptions" in row:
        if not all(isinstance(a, str) for a in row["assumptions"]):
            errors.append(f"[{label}] 'assumptions' must be list of strings.")
        if len(row["assumptions"]) == 0:
            errors.append(f"[{label}] 'assumptions' list is empty — must have entries.")

    if "generated_at" in row and not _iso8601(row["generated_at"]):
        errors.append(f"[{label}] 'generated_at' not valid ISO8601: {row['generated_at']!r}")

    return errors


def _sep(char: str = "-", width: int = 70) -> str:
    return char * width


def main() -> None:
    severities = [0.3, 0.6, 0.9]
    scenario_types = [
        "hormuz_partial_closure",
        "opec_emergency_cut",
        "red_sea_suspension",
    ]

    # Corridor context: supply the relevant corridor per scenario for live
    # risk_score context in the assumptions list.
    corridor_map = {
        "hormuz_partial_closure": "hormuz",
        "opec_emergency_cut":     None,      # OPEC cut is not corridor-specific
        "red_sea_suspension":     "red_sea",
    }

    print(_sep("="))
    print("  Stage 4 — Scenario Modeling Agent: Test Harness")
    print(_sep("="))
    print(f"  Run at: {datetime.now(timezone.utc).isoformat()}")
    print(f"  Scenarios: {scenario_types}")
    print(f"  Severities: {severities}")
    print(f"  Total runs: {len(scenario_types) * len(severities)}\n")

    all_errors: list[str] = []
    results:    list[dict] = []

    # -----------------------------------------------------------------------
    # Run all 9 combinations
    # -----------------------------------------------------------------------
    for stype in scenario_types:
        corridor = corridor_map[stype]

        print(_sep("="))
        print(f"  SCENARIO: {stype.upper()}")
        print(_sep("="))

        scenario_results = []  # for monotonic check
        for sev in severities:
            label = f"{stype}@{sev}"
            try:
                result = run_scenario(stype, sev, corridor=corridor)
            except Exception as exc:
                msg = f"[{label}] run_scenario() raised: {exc}"
                print(f"  [ERROR] {msg}")
                all_errors.append(msg)
                continue

            results.append(result)
            scenario_results.append(result)

            # Print formatted row
            print(f"\n  severity = {sev}")
            print(f"    supply_gap_pct                  : {result['supply_gap_pct']:.4f}  "
                  f"({result['supply_gap_pct']*100:.1f}%)")
            print(f"    price_impact_pct                : {result['price_impact_pct']:.4f}  "
                  f"({result['price_impact_pct']*100:.1f}%)")
            print(f"    refinery_utilization_impact_pct : {result['refinery_utilization_impact_pct']:.4f}  "
                  f"({result['refinery_utilization_impact_pct']*100:.1f}%)")
            print(f"    spr_days_remaining_estimate     : {result['spr_days_remaining_estimate']:.2f} days")

            # Validate
            errs = validate_scenario_row(result, label)
            if errs:
                for e in errs:
                    print(f"    [FAIL] {e}")
                all_errors.extend(errs)
            else:
                print(f"    [PASS] §5 Stage 4 schema valid.")

        # -----------------------------------------------------------------
        # Print assumptions for the highest severity (most detail)
        # -----------------------------------------------------------------
        if scenario_results:
            top_result = scenario_results[-1]  # severity=0.9
            print(f"\n  Assumptions for {stype} @ severity=0.9:")
            for i, assumption in enumerate(top_result["assumptions"], 1):
                print(f"    [{i}] {assumption}")

        # -----------------------------------------------------------------
        # Monotonic sanity check: supply_gap_pct must increase with severity
        # -----------------------------------------------------------------
        print(f"\n  Monotonic supply_gap_pct check for '{stype}':")
        gaps = [r["supply_gap_pct"] for r in scenario_results]
        monotonic_pass = all(gaps[i] < gaps[i+1] for i in range(len(gaps)-1))
        if monotonic_pass:
            print(f"    [PASS] supply_gap_pct increases monotonically: "
                  f"{[f'{g:.4f}' for g in gaps]}")
        else:
            msg = (
                f"[FAIL] supply_gap_pct NOT monotonically increasing for '{stype}': "
                f"{gaps}"
            )
            print(f"    {msg}")
            all_errors.append(msg)

        print()

    # -----------------------------------------------------------------------
    # Print full results table
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  FULL RESULTS TABLE (all 9 runs)")
    print(_sep("="))
    header = (
        f"  {'Scenario':<28} {'Sev':>4}  {'Gap%':>5}  "
        f"{'Price%':>6}  {'Refin%':>6}  {'SPR_days':>8}"
    )
    print(header)
    print("  " + "-" * 65)
    for r in results:
        print(
            f"  {r['scenario_type']:<28} {r['severity']:>4.1f}  "
            f"{r['supply_gap_pct']*100:>5.1f}  "
            f"{r['price_impact_pct']*100:>6.1f}  "
            f"{r['refinery_utilization_impact_pct']*100:>6.1f}  "
            f"{r['spr_days_remaining_estimate']:>8.2f}"
        )

    # -----------------------------------------------------------------------
    # Schema summary
    # -----------------------------------------------------------------------
    print()
    print(_sep("="))
    print("  Schema validation summary")
    print(_sep("-"))
    print(f"  Total runs    : {len(results)}")
    print(f"  Schema errors : {len(all_errors)}")
    if all_errors:
        for e in all_errors:
            print(f"    [FAIL] {e}")
        print("\n[ABORTING] Validation errors — will not write to Supabase.")
        sys.exit(1)
    else:
        print("  [PASS] All 9 runs passed schema validation.\n")

    # -----------------------------------------------------------------------
    # Write to Supabase scenarios table
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  Writing to Supabase: scenarios")
    print(_sep("-"))

    insert_rows = []
    for r in results:
        insert_rows.append({
            "scenario_type":                    r["scenario_type"],
            "severity":                         r["severity"],
            "supply_gap_pct":                   r["supply_gap_pct"],
            "price_impact_pct":                 r["price_impact_pct"],
            "refinery_utilization_impact_pct":  r["refinery_utilization_impact_pct"],
            "spr_days_remaining_estimate":      r["spr_days_remaining_estimate"],
            "assumptions":                      r["assumptions"],
            "generated_at":                     r["generated_at"],
        })

    try:
        write_resp = supabase.table("scenarios").insert(insert_rows).execute()
        written = len(insert_rows)
        print(f"  Wrote {written} scenario row(s) to Supabase.\n")
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
            supabase.table("scenarios")
            .select("*")
            .order("generated_at", desc=True)
            .limit(written + 5)
            .execute()
        )
        read_back = read_resp.data
    except Exception as exc:
        print(f"  [ERROR] Supabase read-back failed: {exc}")
        sys.exit(1)

    assert len(read_back) > 0, "Read-back returned 0 rows."
    print(f"  Read back {len(read_back)} row(s) from scenarios table.\n")

    # Print 2 sample rows (one Hormuz + one Red Sea)
    print(_sep("="))
    print("  Sample rows from Supabase scenarios table")
    print(_sep("-"))
    for row in read_back[:2]:
        print(f"\n  scenario_type : {row.get('scenario_type')}")
        print(f"  severity      : {row.get('severity')}")
        print(f"  supply_gap_pct: {row.get('supply_gap_pct')}")
        print(f"  price_impact  : {row.get('price_impact_pct')}")
        n_assumptions = len(row.get("assumptions") or [])
        print(f"  assumptions   : {n_assumptions} entries")
        print(f"  generated_at  : {row.get('generated_at')}")

    # -----------------------------------------------------------------------
    # Final summary
    # -----------------------------------------------------------------------
    print()
    print(_sep("="))
    print("  SUMMARY")
    print(_sep("="))
    print(f"  Total runs         : {len(results)}")
    print(f"  Schema errors      : {len(all_errors)}")
    print(f"  Monotonic checks   : 3 of 3 passed (hormuz, opec, red_sea)")
    print(f"  Wrote to Supabase  : {written}")
    print(f"  Read back          : {len(read_back)}")
    print()
    print("  [PASS] Stage 4 Scenario Modeling: all checks, write, and round-trip complete.")
    print()


if __name__ == "__main__":
    main()
