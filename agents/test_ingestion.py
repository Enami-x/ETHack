"""
/agents/test_ingestion.py
=========================
CLI test harness for Stage 1 — Data Collection (OFAC + RSS ingesters).

What it does:
  1. Calls fetch_ofac_signals() — prints count, 5 samples with match-reason for each
  2. Calls fetch_rss_signals() for 'hormuz' and 'red_sea' corridors
  3. Validates every returned record against the §5 Stage 1 raw_signals schema
  4. Writes all results to fixtures/raw_signals_live.json
  5. Exits with code 1 if ANY validation error is found

Usage (from repo root):
    python -m agents.test_ingestion
    python agents/test_ingestion.py

No API keys required. No env vars required.
"""

import json
import logging
import pathlib
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Allow running as script or module
# ---------------------------------------------------------------------------
try:
    from agents.ingest_ofac import fetch_ofac_signals, SECONDARY_REMARKS_TERMS
    from agents.ingest_rss import fetch_rss_signals
except ModuleNotFoundError:
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from agents.ingest_ofac import fetch_ofac_signals, SECONDARY_REMARKS_TERMS
    from agents.ingest_rss import fetch_rss_signals


# ---------------------------------------------------------------------------
# Logging setup — INFO level so we see what's happening
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# §5 Stage 1 raw_signals schema definition
# ---------------------------------------------------------------------------

VALID_SOURCES   = {"ais", "ofac", "eia", "price_feed", "mock", "rss"}
VALID_CORRIDORS = {"hormuz", "red_sea", "suez", "other"}

REQUIRED_FIELDS: dict[str, type | tuple] = {
    "id":          str,
    "source":      str,
    "timestamp":   str,
    "corridor":    str,
    "raw_payload": dict,
    "ingested_at": str,
}


# ---------------------------------------------------------------------------
# Schema validator
# ---------------------------------------------------------------------------

def _iso8601(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except (ValueError, AttributeError):
        return False


def validate_raw_signal(record: dict, label: str) -> list[str]:
    """
    Validate a raw_signal record field-by-field against the §5 Stage 1 schema.
    Returns a list of error strings (empty = all good).
    """
    errors: list[str] = []

    # 1. All required keys present
    for field in REQUIRED_FIELDS:
        if field not in record:
            errors.append(f"[{label}] MISSING field: '{field}'")

    # 2. Type checks
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in record:
            continue
        if not isinstance(record[field], expected_type):
            errors.append(
                f"[{label}] Field '{field}': expected {expected_type}, "
                f"got {type(record[field]).__name__} ({record[field]!r})"
            )

    # 3. Enum checks
    if "source" in record and record["source"] not in VALID_SOURCES:
        errors.append(
            f"[{label}] 'source' invalid: '{record['source']}'. "
            f"Expected one of {VALID_SOURCES}"
        )

    if "corridor" in record and record["corridor"] not in VALID_CORRIDORS:
        errors.append(
            f"[{label}] 'corridor' invalid: '{record['corridor']}'. "
            f"Expected one of {VALID_CORRIDORS}"
        )

    # 4. ISO8601 checks
    for ts_field in ("timestamp", "ingested_at"):
        if ts_field in record and isinstance(record[ts_field], str):
            if not _iso8601(record[ts_field]):
                errors.append(
                    f"[{label}] '{ts_field}' is not valid ISO8601: {record[ts_field]!r}"
                )

    # 5. raw_payload must not be empty
    if "raw_payload" in record and isinstance(record["raw_payload"], dict):
        if not record["raw_payload"]:
            errors.append(f"[{label}] 'raw_payload' is empty dict.")

    return errors


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _sep(char: str = "-", width: int = 70) -> str:
    return char * width


def _print_samples(signals: list[dict], n: int = 2) -> None:
    samples = signals[:n]
    for i, sig in enumerate(samples, 1):
        print(f"  Sample {i}:")
        print(json.dumps(sig, indent=4, default=str))
        print()


def _validate_all(signals: list[dict], source_label: str) -> list[str]:
    all_errors: list[str] = []
    for i, sig in enumerate(signals):
        label = f"{source_label}[{i}]"
        errs = validate_raw_signal(sig, label)
        all_errors.extend(errs)
    return all_errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    output_path = (
        pathlib.Path(__file__).parent.parent / "fixtures" / "raw_signals_live.json"
    )

    print(_sep("="))
    print("  Stage 1 — Data Collection Ingestion Test Harness")
    print(_sep("="))
    print(f"  Run at: {datetime.now(timezone.utc).isoformat()}\n")

    all_signals: list[dict] = []
    all_errors:  list[str]  = []

    # =======================================================================
    # OFAC — SDN list
    # =======================================================================
    print(_sep("="))
    print("  Source: OFAC  |  SDN Iran petroleum/shipping filter")
    print(_sep("-"))

    print("  Secondary filter keyword list (whole-word, case-insensitive):")
    print(f"    {', '.join(SECONDARY_REMARKS_TERMS)}\n")

    ofac_signals, match_reasons = fetch_ofac_signals()
    print(f"  Signals retrieved: {len(ofac_signals)}")

    if ofac_signals:
        print(f"\n  5 sample records with match justification:")
        for i, sig in enumerate(ofac_signals[:5], 1):
            ent_num = sig["raw_payload"].get("ent_num", "")
            name    = sig["raw_payload"].get("name", "")
            sdn_t   = sig["raw_payload"].get("sdn_type", "") or "(no type)"
            reason  = match_reasons.get(ent_num, "(unknown)")
            remarks = sig["raw_payload"].get("remarks", "")[:120]
            print(f"  [{i}] ent_num={ent_num}")
            print(f"       name:     {name}")
            print(f"       sdn_type: {sdn_t}")
            print(f"       match:    >>> {reason} <<<")
            print(f"       remarks:  {remarks}...")
            print()
    else:
        print("  (no signals — OFAC download may have failed)\n")

    errs = _validate_all(ofac_signals, "ofac")
    all_errors.extend(errs)
    all_signals.extend(ofac_signals)
    if errs:
        for e in errs:
            print(f"  [FAIL] {e}")
    else:
        print(f"  [PASS] All {len(ofac_signals)} OFAC signals pass schema validation.")
    print()

    # =======================================================================
    # RSS — Hormuz
    # =======================================================================
    print(_sep("="))
    print("  Source: RSS  |  Corridor: hormuz")
    print(_sep("-"))
    rss_hormuz_signals = fetch_rss_signals("hormuz")
    print(f"  Signals retrieved: {len(rss_hormuz_signals)}")
    if rss_hormuz_signals:
        _print_samples(rss_hormuz_signals)
    else:
        print("  (no signals — RSS feeds may have no matching articles)\n")

    errs = _validate_all(rss_hormuz_signals, "rss/hormuz")
    all_errors.extend(errs)
    all_signals.extend(rss_hormuz_signals)
    if errs:
        for e in errs:
            print(f"  [FAIL] {e}")
    else:
        print(f"  [PASS] All {len(rss_hormuz_signals)} RSS/hormuz signals pass schema validation.")
    print()

    # =======================================================================
    # RSS — Red Sea
    # =======================================================================
    print(_sep("="))
    print("  Source: RSS  |  Corridor: red_sea")
    print(_sep("-"))
    rss_red_sea_signals = fetch_rss_signals("red_sea")
    print(f"  Signals retrieved: {len(rss_red_sea_signals)}")
    if rss_red_sea_signals:
        _print_samples(rss_red_sea_signals)
    else:
        print("  (no signals — RSS feeds may have no matching articles)\n")

    errs = _validate_all(rss_red_sea_signals, "rss/red_sea")
    all_errors.extend(errs)
    all_signals.extend(rss_red_sea_signals)
    if errs:
        for e in errs:
            print(f"  [FAIL] {e}")
    else:
        print(f"  [PASS] All {len(rss_red_sea_signals)} RSS/red_sea signals pass schema validation.")
    print()

    # =======================================================================
    # Write combined output
    # =======================================================================
    print(_sep("="))
    print(f"  Writing {len(all_signals)} signals to: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(all_signals, fh, indent=2, default=str)
    print(f"  Written: {output_path}\n")

    # =======================================================================
    # Summary
    # =======================================================================
    print(_sep("="))
    print("  SUMMARY")
    print(_sep("="))
    print(f"  OFAC           : {len(ofac_signals)} signal(s)")
    print(f"  RSS/hormuz     : {len(rss_hormuz_signals)} signal(s)")
    print(f"  RSS/red_sea    : {len(rss_red_sea_signals)} signal(s)")
    print(f"  Total          : {len(all_signals)} signal(s)")
    print(f"  Schema errors  : {len(all_errors)}")
    print()

    if all_errors:
        print("  [FAIL] Schema errors found:")
        for e in all_errors:
            print(f"    - {e}")
        print()
        sys.exit(1)
    else:
        print("  [PASS] All retrieved signals match the §5 Stage 1 raw_signals schema.")
        print()
        sys.exit(0)


if __name__ == "__main__":
    main()
