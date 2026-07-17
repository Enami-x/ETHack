"""
/agents/test_risk_intelligence.py
==================================
CLI test harness for Stage 3 — Risk Intelligence Agent.

What it does:
  1. Loads fixtures/processed_signals_sample.json
  2. Groups signals by corridor
  3. Runs compute_risk_score() for each corridor
  4. Validates each output field-by-field against the §5 Stage 3 schema
  5. Prints a pass/fail summary
  6. Exits with code 1 if ANY validation fails

Usage (from repo root):
    python -m agents.test_risk_intelligence

Or equivalently:
    python agents/test_risk_intelligence.py
"""

import json
import sys
import pathlib
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Import the agent under test
# ---------------------------------------------------------------------------
# Allow running as a script (python agents/test_risk_intelligence.py) OR
# as a module (python -m agents.test_risk_intelligence) from the repo root.
try:
    from agents.risk_intelligence import compute_risk_score, SIGNAL_TYPE_WEIGHTS
except ModuleNotFoundError:
    # Running as a plain script; add repo root to path
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from agents.risk_intelligence import compute_risk_score, SIGNAL_TYPE_WEIGHTS


# ---------------------------------------------------------------------------
# §5 Stage 3 schema definition — used for field-by-field validation
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: dict[str, type | tuple] = {
    "id":                   str,
    "corridor":             str,
    "supplier":             (str, type(None)),   # "string | null"
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
    """Return True if value is a parseable ISO-8601 datetime string."""
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except (ValueError, AttributeError):
        return False


def validate_risk_score_row(row: dict, label: str) -> list[str]:
    """
    Validate a risk_scores row field-by-field against the §5 Stage 3 schema.
    Returns a list of error strings (empty list = all good).
    """
    errors: list[str] = []

    # 1. All required keys present
    for field in REQUIRED_FIELDS:
        if field not in row:
            errors.append(f"[{label}] MISSING field: '{field}'")

    # 2. Type checks
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in row:
            continue
        value = row[field]
        if not isinstance(value, expected_type):
            errors.append(
                f"[{label}] Field '{field}': expected {expected_type}, "
                f"got {type(value).__name__} ({value!r})"
            )

    # 3. Semantic / value-range checks
    if "risk_score" in row:
        if not (0.0 <= row["risk_score"] <= 1.0):
            errors.append(
                f"[{label}] 'risk_score' out of range [0,1]: {row['risk_score']}"
            )

    if "confidence" in row:
        if not (0.0 <= row["confidence"] <= 1.0):
            errors.append(
                f"[{label}] 'confidence' out of range [0,1]: {row['confidence']}"
            )

    if "corridor" in row:
        if row["corridor"] not in VALID_CORRIDORS:
            errors.append(
                f"[{label}] 'corridor' invalid value '{row['corridor']}'. "
                f"Expected one of {VALID_CORRIDORS}"
            )

    if "source" in row:
        if row["source"] not in VALID_SOURCES:
            errors.append(
                f"[{label}] 'source' invalid value '{row['source']}'. "
                f"Expected one of {VALID_SOURCES}"
            )

    if "generated_at" in row:
        if not _iso8601(row["generated_at"]):
            errors.append(
                f"[{label}] 'generated_at' is not a valid ISO8601 string: "
                f"{row['generated_at']!r}"
            )

    if "contributing_signals" in row:
        if not all(isinstance(s, str) for s in row["contributing_signals"]):
            errors.append(
                f"[{label}] 'contributing_signals' must be a list of strings."
            )

    return errors


def _sep(char: str = "-", width: int = 70) -> str:
    return char * width


def main() -> None:
    # -----------------------------------------------------------------------
    # Load fixture
    # -----------------------------------------------------------------------
    fixture_path = (
        pathlib.Path(__file__).parent.parent / "fixtures" / "processed_signals_sample.json"
    )
    print(_sep("="))
    print("  Stage 3 — Risk Intelligence Agent: Test Harness")
    print(_sep("="))
    print(f"\nLoading fixture: {fixture_path}")

    with open(fixture_path, "r", encoding="utf-8") as fh:
        signals: list[dict] = json.load(fh)

    print(f"Loaded {len(signals)} signal(s).\n")

    # -----------------------------------------------------------------------
    # Echo active weight constants
    # -----------------------------------------------------------------------
    print(_sep("-"))
    print("  Weight constants (SIGNAL_TYPE_WEIGHTS):")
    for stype, w in SIGNAL_TYPE_WEIGHTS.items():
        print(f"    {stype:<12} = {w}")
    print(_sep("-"))

    # -----------------------------------------------------------------------
    # Group by corridor
    # -----------------------------------------------------------------------
    grouped: dict[str, list[dict]] = {}
    for sig in signals:
        corridor = sig.get("corridor", "unknown")
        grouped.setdefault(corridor, []).append(sig)

    print(f"\nCorridors found: {sorted(grouped.keys())}\n")

    # -----------------------------------------------------------------------
    # Run compute_risk_score() per corridor, validate, print
    # -----------------------------------------------------------------------
    all_errors: list[str] = []
    results: list[dict] = []

    for corridor, corridor_signals in sorted(grouped.items()):
        print(_sep("="))
        print(f"  CORRIDOR: {corridor.upper()}  ({len(corridor_signals)} signal(s))")
        print(_sep("="))

        try:
            result = compute_risk_score(corridor_signals)
        except Exception as exc:
            msg = f"[{corridor}] compute_risk_score() raised: {exc}"
            print(f"  ERROR: {msg}")
            all_errors.append(msg)
            continue

        results.append(result)

        # Pretty-print result
        print(json.dumps(result, indent=2, default=str))

        # Validate
        errors = validate_risk_score_row(result, corridor)
        if errors:
            for e in errors:
                print(f"  [FAIL] {e}")
            all_errors.extend(errors)
        else:
            print(f"\n  [PASS] All §5 Stage 3 schema checks passed for '{corridor}'.")

        print()

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  SUMMARY")
    print(_sep("="))
    print(f"  Corridors tested : {len(grouped)}")
    print(f"  Results produced : {len(results)}")
    print(f"  Schema errors    : {len(all_errors)}")
    print()

    if all_errors:
        print("  [FAIL] Errors:")
        for e in all_errors:
            print(f"    - {e}")
        print()
        sys.exit(1)
    else:
        print("  [PASS] All outputs match the §5 Stage 3 risk_scores schema.")
        print()
        sys.exit(0)


if __name__ == "__main__":
    main()
