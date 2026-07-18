"""
/agents/test_normalize.py
==========================
CLI test harness for Stage 2 — Data Processing (normalize_signals) + Supabase write.

What it does:
  1. Loads fixtures/raw_signals_live.json (Stage 1 output)
  2. Calls normalize_signals() to produce Stage 2 processed_signals
  3. Prints OFAC aggregated signals (one per corridor) + 3 sample RSS signals
  4. Validates all output rows against the §5 Stage 2 schema
  5. Writes all processed signals to Supabase processed_signals table
  6. Reads back from Supabase to confirm round-trip
  7. Prints counts: "Wrote X, read back X"

Usage (from repo root):
    python -m agents.test_normalize

Requires: .env with SUPABASE_URL and SUPABASE_SERVICE_KEY
          fixtures/raw_signals_live.json (run test_ingestion.py first if missing)
"""

import json
import logging
import pathlib
import sys
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allow running as script or module
# ---------------------------------------------------------------------------
try:
    from agents.normalize_signals import normalize_signals
    from db.supabase_client import supabase
except ModuleNotFoundError:
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from agents.normalize_signals import normalize_signals
    from db.supabase_client import supabase


# ---------------------------------------------------------------------------
# §5 Stage 2 schema definition for validation
# ---------------------------------------------------------------------------
VALID_CORRIDORS    = {"hormuz", "red_sea", "suez", "other"}
VALID_SIGNAL_TYPES = {"news", "shipping", "sanctions", "price"}

REQUIRED_FIELDS: dict[str, type] = {
    "id":                   str,
    "corridor":             str,
    "signal_type":          str,
    "severity_hint":        float,
    "text_summary":         str,
    "contributing_signals": list,
    "source":               str,
    "generated_at":         str,
}


def validate_processed_signal(record: dict, label: str) -> list[str]:
    errors: list[str] = []
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in record:
            errors.append(f"[{label}] MISSING field: '{field}'")
        elif not isinstance(record[field], expected_type):
            errors.append(
                f"[{label}] '{field}': expected {expected_type.__name__}, "
                f"got {type(record[field]).__name__}"
            )
    if "corridor" in record and record["corridor"] not in VALID_CORRIDORS:
        errors.append(f"[{label}] 'corridor' invalid: '{record['corridor']}'")
    if "signal_type" in record and record["signal_type"] not in VALID_SIGNAL_TYPES:
        errors.append(f"[{label}] 'signal_type' invalid: '{record['signal_type']}'")
    if "severity_hint" in record:
        sh = record["severity_hint"]
        if not (0.0 <= sh <= 1.0):
            errors.append(f"[{label}] 'severity_hint' out of range [0,1]: {sh}")
    return errors


def _sep(char: str = "-", width: int = 70) -> str:
    return char * width


def main() -> None:
    fixture_path = (
        pathlib.Path(__file__).parent.parent / "fixtures" / "raw_signals_live.json"
    )
    if not fixture_path.exists():
        print(f"[ERROR] Fixture not found: {fixture_path}")
        print("  Run 'python -m agents.test_ingestion' first to generate it.")
        sys.exit(1)

    print(_sep("="))
    print("  Stage 2 — Normalisation + Supabase Write Test Harness")
    print(_sep("="))
    print(f"  Run at: {datetime.now(timezone.utc).isoformat()}\n")

    # -----------------------------------------------------------------------
    # Load raw signals
    # -----------------------------------------------------------------------
    print(f"  Loading raw signals from: {fixture_path}")
    with open(fixture_path, encoding="utf-8") as fh:
        raw_signals = json.load(fh)
    print(f"  Loaded {len(raw_signals)} raw signals.\n")

    # -----------------------------------------------------------------------
    # Normalise
    # -----------------------------------------------------------------------
    processed = normalize_signals(raw_signals)
    print(f"  normalize_signals() produced {len(processed)} processed signal(s).\n")

    # -----------------------------------------------------------------------
    # Show OFAC aggregated signals (sanctions type)
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  OFAC aggregated signals (one per corridor)")
    print(_sep("-"))
    ofac_processed = [s for s in processed if s["signal_type"] == "sanctions"]
    print(f"  Count: {len(ofac_processed)} corridor aggregate(s)\n")
    for sig in ofac_processed:
        contributing_count = len(sig.get("contributing_signals", []))
        print(f"  corridor={sig['corridor']}")
        print(f"    signal_type  : {sig['signal_type']}")
        print(f"    severity_hint: {sig['severity_hint']}")
        print(f"    text_summary : {sig['text_summary']}")
        print(f"    contributing : {contributing_count} raw_signal IDs")
        print(f"    source       : {sig['source']}")
        print()

    # -----------------------------------------------------------------------
    # Show 3 sample RSS news signals
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  Sample RSS news signals (first 3)")
    print(_sep("-"))
    rss_processed = [s for s in processed if s["signal_type"] == "news"]
    print(f"  Total RSS signals: {len(rss_processed)}\n")
    for i, sig in enumerate(rss_processed[:3], 1):
        print(f"  [{i}] corridor={sig['corridor']}")
        print(f"       signal_type  : {sig['signal_type']}")
        print(f"       severity_hint: {sig['severity_hint']}")
        print(f"       text_summary : {sig['text_summary']}")
        print(f"       source       : {sig['source']}")
        print()

    # -----------------------------------------------------------------------
    # Validate all
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  Schema validation (§5 Stage 2)")
    print(_sep("-"))
    all_errors: list[str] = []
    for i, sig in enumerate(processed):
        errs = validate_processed_signal(sig, f"processed[{i}]")
        all_errors.extend(errs)

    if all_errors:
        for e in all_errors:
            print(f"  [FAIL] {e}")
        print()
    else:
        print(f"  [PASS] All {len(processed)} processed signals pass schema validation.\n")

    if all_errors:
        print("[ABORTING] Validation errors found — will not write to Supabase.")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Write to Supabase
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  Writing to Supabase: processed_signals")
    print(_sep("-"))

    # Supabase insert payload — strip Python-only 'id' field (DB generates UUID)
    # and convert ISO string generated_at to let Supabase handle the timestamptz
    insert_rows = []
    for sig in processed:
        row = {
            "corridor":             sig["corridor"],
            "signal_type":          sig["signal_type"],
            "severity_hint":        sig["severity_hint"],
            "text_summary":         sig["text_summary"],
            "contributing_signals": sig["contributing_signals"],
            "source":               sig["source"],
            "generated_at":         sig["generated_at"],
        }
        insert_rows.append(row)

    # Insert in batches of 500 to avoid Supabase payload size limits
    BATCH_SIZE = 500
    written = 0
    for i in range(0, len(insert_rows), BATCH_SIZE):
        batch = insert_rows[i : i + BATCH_SIZE]
        try:
            response = supabase.table("processed_signals").insert(batch).execute()
            written += len(batch)
            print(f"  Batch {i // BATCH_SIZE + 1}: inserted {len(batch)} rows.")
        except Exception as exc:
            print(f"  [ERROR] Supabase insert failed at batch {i // BATCH_SIZE + 1}: {exc}")
            sys.exit(1)

    print(f"\n  Total written to Supabase: {written}\n")

    # -----------------------------------------------------------------------
    # Read back to confirm round-trip
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  Reading back from Supabase to confirm round-trip")
    print(_sep("-"))
    try:
        read_response = (
            supabase.table("processed_signals")
            .select("*")
            .order("generated_at", desc=True)
            .limit(written + 10)
            .execute()
        )
        read_back = read_response.data
    except Exception as exc:
        print(f"  [ERROR] Supabase read failed: {exc}")
        sys.exit(1)

    assert len(read_back) > 0, "Read-back returned 0 rows — something went wrong."
    print(f"  Read back {len(read_back)} row(s) from processed_signals.\n")

    # -----------------------------------------------------------------------
    # Print 2 samples from Supabase (one OFAC + one RSS)
    # -----------------------------------------------------------------------
    print(_sep("="))
    print("  2 sample rows from Supabase (one OFAC aggregate + one RSS news)")
    print(_sep("-"))
    ofac_row = next((r for r in read_back if r["signal_type"] == "sanctions"), None)
    rss_row  = next((r for r in read_back if r["signal_type"] == "news"), None)

    for label, row in [("OFAC aggregate", ofac_row), ("RSS news", rss_row)]:
        if row:
            print(f"\n  [{label}]")
            print(json.dumps(
                {k: v for k, v in row.items() if k != "contributing_signals"},
                indent=4, default=str
            ))
            if row.get("contributing_signals"):
                print(f"    contributing_signals: [{len(row['contributing_signals'])} IDs]")
        else:
            print(f"\n  [{label}]: (not found in read-back)")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print()
    print(_sep("="))
    print("  SUMMARY")
    print(_sep("="))
    print(f"  Raw signals loaded      : {len(raw_signals)}")
    print(f"  Processed signals built : {len(processed)}")
    print(f"    - sanctions (OFAC agg): {len(ofac_processed)}")
    print(f"    - news (RSS)          : {len(rss_processed)}")
    print(f"  Schema errors           : {len(all_errors)}")
    print(f"  Wrote to Supabase       : {written}")
    print(f"  Read back from Supabase : {len(read_back)}")
    print()
    print("  [PASS] Stage 2 normalisation + Supabase round-trip complete.")
    print()


if __name__ == "__main__":
    main()
