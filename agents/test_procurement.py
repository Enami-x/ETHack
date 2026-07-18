"""
/agents/test_procurement.py
============================
CLI test harness for Stage 5 — Procurement Orchestrator.

What it does:
  1. Loads fixtures/suppliers.json
  2. Fetches the most recent hormuz_partial_closure scenario (severity=0.9) from Supabase
  3. Runs rank_suppliers() to produce ranked procurement recommendations
  4. Prints the full ranked table (rank, supplier, score, corridor_exposure, rationale)
  5. SANITY CHECK: asserts Saudi Arabia AND UAE do NOT rank #1 in a Hormuz scenario
     with severity >= 0.6 — fails loudly if corridor penalty logic is broken
  6. Validates each output row against the §5 Stage 5 schema
  7. Writes all recommendations to the procurement_recs Supabase table
  8. Reads back to confirm round-trip

Usage (from repo root):
    python -m agents.test_procurement

Requires: .env with SUPABASE_URL and SUPABASE_SERVICE_KEY
          fixtures/suppliers.json (committed to repo)
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
    from agents.procurement_orchestrator import rank_suppliers, WEIGHTS
    from db.supabase_client import supabase
except ModuleNotFoundError:
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from agents.procurement_orchestrator import rank_suppliers, WEIGHTS
    from db.supabase_client import supabase

REPO_ROOT     = pathlib.Path(__file__).parent.parent
SUPPLIER_PATH = REPO_ROOT / "fixtures" / "suppliers.json"


# ---------------------------------------------------------------------------
# §5 Stage 5 schema — field-by-field validator
# ---------------------------------------------------------------------------
REQUIRED_FIELDS: dict[str, type | tuple] = {
    "id":                           str,
    "scenario_id":                  (str, type(None)),
    "rank":                         int,
    "supplier":                     str,
    "route":                        str,
    "spot_price_est":               float,
    "transit_time_days":            float,
    "refinery_compatibility_score": float,
    "overall_score":                float,
    "rationale":                    str,
    "source":                       str,
    "generated_at":                 str,
}
VALID_SOURCES = {"real", "mock"}


def _iso8601(v: str) -> bool:
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return True
    except (ValueError, AttributeError):
        return False


def validate_procurement_row(row: dict, label: str) -> list[str]:
    errors: list[str] = []
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in row:
            errors.append(f"[{label}] MISSING field: '{field}'")
        elif not isinstance(row[field], expected_type):
            errors.append(
                f"[{label}] '{field}': expected {expected_type}, "
                f"got {type(row[field]).__name__}"
            )
    if "rank" in row and row["rank"] < 1:
        errors.append(f"[{label}] 'rank' must be >= 1, got {row['rank']}")
    if "overall_score" in row and not (0.0 <= row["overall_score"] <= 1.0):
        errors.append(f"[{label}] 'overall_score' out of [0,1]: {row['overall_score']}")
    if "source" in row and row["source"] not in VALID_SOURCES:
        errors.append(f"[{label}] 'source' invalid: '{row['source']}'")
    if "generated_at" in row and not _iso8601(row["generated_at"]):
        errors.append(f"[{label}] 'generated_at' not ISO8601: {row['generated_at']!r}")
    return errors


def _sep(char: str = "-", width: int = 70) -> str:
    return char * width


def main() -> None:
    print(_sep("="))
    print("  Stage 5 — Procurement Orchestrator: Test Harness")
    print(_sep("="))
    print(f"  Run at: {datetime.now(timezone.utc).isoformat()}\n")

    # -----------------------------------------------------------------------
    # 1. Load suppliers fixture
    # -----------------------------------------------------------------------
    if not SUPPLIER_PATH.exists():
        print(f"  [ERROR] Supplier fixture not found: {SUPPLIER_PATH}")
        sys.exit(1)

    with open(SUPPLIER_PATH, encoding="utf-8") as fh:
        suppliers: list[dict] = json.load(fh)
    print(f"  Loaded {len(suppliers)} suppliers from {SUPPLIER_PATH.name}.\n")

    # -----------------------------------------------------------------------
    # 2. Fetch most recent hormuz_partial_closure @ severity=0.9 from Supabase
    # -----------------------------------------------------------------------
    print("  Fetching hormuz_partial_closure scenario (severity=0.9) from Supabase...")
    try:
        resp = (
            supabase.table("scenarios")
            .select("*")
            .eq("scenario_type", "hormuz_partial_closure")
            .eq("severity", 0.9)
            .order("generated_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = resp.data
    except Exception as exc:
        print(f"  [ERROR] Supabase read failed: {exc}")
        sys.exit(1)

    if not rows:
        print("  [ERROR] No hormuz_partial_closure scenario with severity=0.9 found.")
        print("  Run 'python -m agents.test_scenario_modeling' first.")
        sys.exit(1)

    scenario = rows[0]
    print(f"  Found scenario: id={scenario['id']}")
    print(f"    scenario_type: {scenario['scenario_type']}")
    print(f"    severity     : {scenario['severity']}")
    print(f"    supply_gap   : {scenario['supply_gap_pct']}")
    print(f"    generated_at : {scenario['generated_at']}\n")

    # -----------------------------------------------------------------------
    # 3. Echo scoring weights
    # -----------------------------------------------------------------------
    print(_sep("-"))
    print("  Scoring weights (WEIGHTS):")
    for dim, w in WEIGHTS.items():
        print(f"    {dim:<20} = {w}")
    print(_sep("-"))

    # -----------------------------------------------------------------------
    # 4. Run rank_suppliers()
    # -----------------------------------------------------------------------
    print("\n  Running rank_suppliers()...")
    try:
        ranked = rank_suppliers(scenario, suppliers)
    except Exception as exc:
        print(f"  [ERROR] rank_suppliers() raised: {exc}")
        sys.exit(1)

    print(f"  Produced {len(ranked)} procurement recommendations.\n")

    # -----------------------------------------------------------------------
    # 5. Print full ranked table
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  FULL RANKED TABLE — hormuz_partial_closure severity=0.9")
    print(_sep("="))
    header = f"  {'Rank':>4}  {'Supplier':<15}  {'Score':>6}  {'Price':>6}  {'Transit':>7}  {'Compat':>6}  {'Corridor_dep'}"
    print(header)
    print("  " + "-" * 68)

    # Load suppliers dict for lookup
    sup_by_name = {s["supplier"]: s for s in suppliers}

    for row in ranked:
        sup_data = sup_by_name.get(row["supplier"], {})
        dep = sup_data.get("corridor_dependency", [])
        dep_str = ",".join(dep) if dep else "none"
        print(
            f"  {row['rank']:>4}  {row['supplier']:<15}  "
            f"{row['overall_score']:>6.4f}  "
            f"${row['spot_price_est']:>5.2f}  "
            f"{row['transit_time_days']:>5.0f}d  "
            f"{row['refinery_compatibility_score']:>6.2f}  "
            f"[{dep_str}]"
        )

    # -----------------------------------------------------------------------
    # 6. Print rationale for each ranked supplier
    # -----------------------------------------------------------------------
    print()
    print(_sep("="))
    print("  RATIONALE PER SUPPLIER")
    print(_sep("="))
    for row in ranked:
        print(f"\n  Rank #{row['rank']}: {row['supplier']}")
        print(f"  Route: {row['route']}")
        # Wrap rationale at 80 chars
        rat = row["rationale"]
        words, line = [], ""
        for word in rat.split():
            if len(line) + len(word) + 1 > 78:
                print(f"    {line}")
                line = word
            else:
                line = (line + " " + word).strip()
        if line:
            print(f"    {line}")

    # -----------------------------------------------------------------------
    # 7. SANITY CHECK: Saudi Arabia and UAE must NOT rank #1 for Hormuz ≥0.6
    # -----------------------------------------------------------------------
    print()
    print(_sep("="))
    print("  SANITY CHECK: Hormuz-exposed suppliers must not rank #1")
    print(_sep("-"))

    top_supplier = ranked[0]["supplier"]
    hormuz_exposed = {"Saudi Arabia", "UAE", "Iraq"}
    severity_val   = float(scenario["severity"])

    if severity_val >= 0.6 and top_supplier in hormuz_exposed:
        msg = (
            f"[FAIL] SANITY CHECK FAILED: '{top_supplier}' ranked #1 in a "
            f"hormuz_partial_closure scenario with severity={severity_val:.1f}. "
            f"Corridor penalty logic is broken."
        )
        print(f"  {msg}")
        sys.exit(1)
    else:
        print(
            f"  [PASS] Top-ranked supplier is '{top_supplier}' — "
            f"not Hormuz-exposed. Corridor penalty logic is working correctly."
        )
        # Also confirm Saudi Arabia and UAE are not in top 3
        top3 = {r["supplier"] for r in ranked[:3]}
        exposed_in_top3 = top3 & hormuz_exposed
        if exposed_in_top3 and severity_val >= 0.6:
            print(
                f"  [WARN] Hormuz-exposed suppliers {exposed_in_top3} appear in top 3. "
                f"Consider increasing CORRIDOR_PENALTY_SCALE."
            )
        else:
            print(
                f"  [PASS] No Hormuz-exposed supplier in top 3. "
                f"Top 3: {[r['supplier'] for r in ranked[:3]]}"
            )

    # -----------------------------------------------------------------------
    # 8. Schema validation
    # -----------------------------------------------------------------------
    print()
    print(_sep("="))
    print("  Schema validation (§5 Stage 5)")
    print(_sep("-"))
    all_errors: list[str] = []
    for row in ranked:
        errs = validate_procurement_row(row, f"rank_{row['rank']}_{row['supplier']}")
        all_errors.extend(errs)

    if all_errors:
        for e in all_errors:
            print(f"  [FAIL] {e}")
        print("\n[ABORTING] Validation errors — not writing to Supabase.")
        sys.exit(1)
    else:
        print(f"  [PASS] All {len(ranked)} rows passed §5 Stage 5 schema validation.\n")

    # -----------------------------------------------------------------------
    # 9. Write to Supabase procurement_recs
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  Writing to Supabase: procurement_recs")
    print(_sep("-"))

    insert_rows = []
    for row in ranked:
        insert_rows.append({
            "scenario_id":                  row["scenario_id"],
            "rank":                         row["rank"],
            "supplier":                     row["supplier"],
            "route":                        row["route"],
            "spot_price_est":               row["spot_price_est"],
            "transit_time_days":            row["transit_time_days"],
            "refinery_compatibility_score": row["refinery_compatibility_score"],
            "overall_score":                row["overall_score"],
            "rationale":                    row["rationale"],
            "source":                       row["source"],
            "generated_at":                 row["generated_at"],
        })

    try:
        supabase.table("procurement_recs").insert(insert_rows).execute()
        written = len(insert_rows)
        print(f"  Wrote {written} recommendation row(s) to Supabase.\n")
    except Exception as exc:
        print(f"  [ERROR] Supabase write failed: {exc}")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # 10. Read back to confirm round-trip
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  Reading back from Supabase (round-trip check)")
    print(_sep("-"))
    try:
        read_resp = (
            supabase.table("procurement_recs")
            .select("rank, supplier, overall_score, source, generated_at")
            .eq("scenario_id", scenario["id"])
            .order("rank")
            .execute()
        )
        read_back = read_resp.data
    except Exception as exc:
        print(f"  [ERROR] Supabase read-back failed: {exc}")
        sys.exit(1)

    print(f"  Read back {len(read_back)} row(s) from procurement_recs.\n")
    print("  Supabase round-trip sample:")
    for rb in read_back[:3]:
        print(f"    Rank #{rb['rank']:>2}: {rb['supplier']:<15} score={rb['overall_score']:.4f}")

    # -----------------------------------------------------------------------
    # 11. Final summary
    # -----------------------------------------------------------------------
    print()
    print(_sep("="))
    print("  SUMMARY")
    print(_sep("="))
    print(f"  Suppliers loaded          : {len(suppliers)}")
    print(f"  Recommendations produced  : {len(ranked)}")
    print(f"  Schema errors             : {len(all_errors)}")
    print(f"  Sanity check              : PASS (Saudi Arabia/UAE not ranked #1)")
    print(f"  Wrote to Supabase         : {written}")
    print(f"  Read back                 : {len(read_back)}")
    print()
    print("  [PASS] Stage 5 Procurement Orchestrator: all checks, write, and round-trip complete.")
    print()


if __name__ == "__main__":
    main()
