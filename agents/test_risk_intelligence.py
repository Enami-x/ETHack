"""
/agents/test_risk_intelligence.py
==================================
CLI test harness for Stage 3 — Risk Intelligence Agent (live Supabase + Gemini).

What it does:
  1. Reads processed_signals from Supabase
  2. Groups signals by corridor
  3. Runs compute_risk_score(use_llm=True) per corridor (calls Gemini for explanation)
  4. Prints each result including full Gemini-generated explanation
  5. Validates each output against the §5 Stage 3 risk_scores schema
  6. Writes results to the risk_scores Supabase table
  7. Reads back from Supabase to confirm round-trip
  8. Exits with code 1 if ANY validation fails

Usage (from repo root):
    python -m agents.test_risk_intelligence

Requires: .env with SUPABASE_URL, SUPABASE_SERVICE_KEY, GEMINI_API_KEY
"""

import json
import logging
import sys
import time
import pathlib
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Imports — allow running as script OR module
# ---------------------------------------------------------------------------
try:
    from agents.risk_intelligence import compute_risk_score, SIGNAL_TYPE_WEIGHTS
    from db.supabase_client import supabase
except ModuleNotFoundError:
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from agents.risk_intelligence import compute_risk_score, SIGNAL_TYPE_WEIGHTS
    from db.supabase_client import supabase


# ---------------------------------------------------------------------------
# §5 Stage 3 schema — field-by-field validator
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: dict[str, type | tuple] = {
    "id":                   str,
    "corridor":             str,
    "supplier":             (str, type(None)),
    "risk_score":           float,
    "confidence":           float,
    "explanation":          str,
    "contributing_signals": list,
    "source":               str,
    "generated_at":         str,
}

VALID_CORRIDORS = {"hormuz", "red_sea", "suez", "other"}
VALID_SOURCES   = {"real", "mock"}


def _iso8601(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except (ValueError, AttributeError):
        return False


def validate_risk_score_row(row: dict, label: str) -> list[str]:
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in row:
            errors.append(f"[{label}] MISSING field: '{field}'")

    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in row:
            continue
        value = row[field]
        if not isinstance(value, expected_type):
            errors.append(
                f"[{label}] Field '{field}': expected {expected_type}, "
                f"got {type(value).__name__} ({value!r})"
            )

    if "risk_score" in row and not (0.0 <= row["risk_score"] <= 1.0):
        errors.append(f"[{label}] 'risk_score' out of range [0,1]: {row['risk_score']}")

    if "confidence" in row and not (0.0 <= row["confidence"] <= 1.0):
        errors.append(f"[{label}] 'confidence' out of range [0,1]: {row['confidence']}")

    if "corridor" in row and row["corridor"] not in VALID_CORRIDORS:
        errors.append(f"[{label}] 'corridor' invalid: '{row['corridor']}'")

    if "source" in row and row["source"] not in VALID_SOURCES:
        errors.append(f"[{label}] 'source' invalid: '{row['source']}'")

    if "generated_at" in row and not _iso8601(row["generated_at"]):
        errors.append(f"[{label}] 'generated_at' not valid ISO8601: {row['generated_at']!r}")

    if "contributing_signals" in row:
        if not all(isinstance(s, str) for s in row["contributing_signals"]):
            errors.append(f"[{label}] 'contributing_signals' must be list of strings.")

    return errors


def _sep(char: str = "-", width: int = 70) -> str:
    return char * width


def main() -> None:
    print(_sep("="))
    print("  Stage 3 — Risk Intelligence Agent: Live Test (Supabase + Gemini)")
    print(_sep("="))
    print(f"  Run at: {datetime.now(timezone.utc).isoformat()}\n")

    # -----------------------------------------------------------------------
    # 1. Read processed_signals from Supabase
    # -----------------------------------------------------------------------
    print("  Reading processed_signals from Supabase...")
    try:
        response = supabase.table("processed_signals").select("*").execute()
        processed_signals: list[dict] = response.data
    except Exception as exc:
        print(f"  [ERROR] Supabase read failed: {exc}")
        sys.exit(1)

    print(f"  Loaded {len(processed_signals)} processed signal(s) from Supabase.\n")

    if not processed_signals:
        print("  [ERROR] No processed signals found. Run test_normalize.py first.")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # 2. Echo weight constants
    # -----------------------------------------------------------------------
    print(_sep("-"))
    print("  Weight constants (SIGNAL_TYPE_WEIGHTS):")
    for stype, w in SIGNAL_TYPE_WEIGHTS.items():
        print(f"    {stype:<12} = {w}")
    print(_sep("-"))

    # -----------------------------------------------------------------------
    # 3. Group by corridor
    # -----------------------------------------------------------------------
    grouped: dict[str, list[dict]] = {}
    for sig in processed_signals:
        corridor = sig.get("corridor", "unknown")
        grouped.setdefault(corridor, []).append(sig)

    print(f"\n  Corridors found: {sorted(grouped.keys())}\n")

    # -----------------------------------------------------------------------
    # 4. Compute risk scores per corridor (with Gemini explanations)
    # -----------------------------------------------------------------------
    all_errors: list[str] = []
    results:    list[dict] = []

    for corridor, corridor_signals in sorted(grouped.items()):
        print(_sep("="))
        print(f"  CORRIDOR: {corridor.upper()}  ({len(corridor_signals)} signal(s))")
        print(_sep("="))

        try:
            result = compute_risk_score(corridor_signals, use_llm=True)
            # Add a small delay after calling the LLM to respect free tier rate limits
            time.sleep(3)
        except Exception as exc:
            msg = f"[{corridor}] compute_risk_score() raised: {exc}"
            print(f"  ERROR: {msg}")
            all_errors.append(msg)
            continue

        results.append(result)

        # Print key fields prominently
        print(f"  risk_score   : {result['risk_score']}")
        print(f"  confidence   : {result['confidence']}")
        print(f"  source       : {result['source']}")
        print(f"  signals used : {len(result['contributing_signals'])}")
        print()
        print("  EXPLANATION (Gemini-generated):")
        print("  " + result["explanation"].replace("\n", "\n  "))
        print()

        errors = validate_risk_score_row(result, corridor)
        if errors:
            for e in errors:
                print(f"  [FAIL] {e}")
            all_errors.extend(errors)
        else:
            print(f"  [PASS] §5 Stage 3 schema checks passed for '{corridor}'.")
        print()

    if all_errors:
        print("[ABORTING] Validation errors — will not write to Supabase.")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # 5. Write risk_scores to Supabase
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  Writing risk_scores to Supabase")
    print(_sep("-"))

    insert_rows = []
    for r in results:
        insert_rows.append({
            "corridor":             r["corridor"],
            "supplier":             r["supplier"],
            "risk_score":           r["risk_score"],
            "confidence":           r["confidence"],
            "explanation":          r["explanation"],
            "contributing_signals": r["contributing_signals"],
            "source":               r["source"],
            "generated_at":         r["generated_at"],
        })

    try:
        write_resp = supabase.table("risk_scores").insert(insert_rows).execute()
        written = len(insert_rows)
        print(f"  Wrote {written} risk_score row(s) to Supabase.\n")
    except Exception as exc:
        print(f"  [ERROR] Supabase write failed: {exc}")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # 6. Read back to confirm round-trip
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  Reading back risk_scores from Supabase (round-trip check)")
    print(_sep("-"))
    try:
        read_resp = (
            supabase.table("risk_scores")
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
    print(f"  Read back {len(read_back)} row(s) from risk_scores.\n")

    # Print 2 sample rows from Supabase (one per corridor type)
    print(_sep("="))
    print("  Sample rows from Supabase risk_scores table")
    print(_sep("-"))
    for row in read_back[:2]:
        print(f"\n  corridor    : {row.get('corridor')}")
        print(f"  risk_score  : {row.get('risk_score')}")
        print(f"  confidence  : {row.get('confidence')}")
        print(f"  source      : {row.get('source')}")
        print(f"  generated_at: {row.get('generated_at')}")
        n_contributing = len(row.get("contributing_signals") or [])
        print(f"  contributing: {n_contributing} signal ID(s)")
        print(f"  explanation :")
        print("    " + str(row.get("explanation", "")).replace("\n", "\n    "))

    # -----------------------------------------------------------------------
    # 7. Summary
    # -----------------------------------------------------------------------
    print()
    print(_sep("="))
    print("  SUMMARY")
    print(_sep("="))
    print(f"  Processed signals read from Supabase : {len(processed_signals)}")
    print(f"  Corridors scored                     : {len(grouped)}")
    print(f"  Risk score rows produced             : {len(results)}")
    print(f"  Schema errors                        : {len(all_errors)}")
    print(f"  Wrote to risk_scores (Supabase)      : {written}")
    print(f"  Read back from risk_scores           : {len(read_back)}")
    print()
    print("  [PASS] Stage 3 Risk Intelligence: Supabase read + Gemini + write + round-trip complete.")
    print()


if __name__ == "__main__":
    main()
