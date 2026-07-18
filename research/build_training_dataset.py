"""
/research/build_training_dataset.py
=====================================
Build a historical disruption training dataset for ML from EIA production data
and Brent crude price history.

Pipeline:
  1. Load research/known_disruption_events.json  (18 seed events 2015-2026)
  2. Load research/brent_prices.csv.csv          (daily Brent OHLCV, MM/DD/YYYY)
  3. Load research/eia_production.csv.csv        (EIA Non-OPEC + Middle East monthly)
  4. For each event:
       - Locate Brent price on the event date (or nearest trading day)
       - Locate Brent price ~30 days later
       - Compute price_change_pct = (price_30d - price_event) / price_event
       - Locate the EIA row for affected_producer
       - Get production volume at the event month and 1 month later
       - Compute volume_change_pct = (vol_after - vol_at_event) / vol_at_event
       - Assign data_quality: "complete" | "partial" | "no_data"
  5. Output research/historical_disruptions.json
  6. Print summary table + counts

Data quality rules:
  - "complete": both price AND volume data available
  - "partial":  one of the two is available
  - "no_data":  neither is available (e.g. event date outside CSV range)

Notes on the EIA CSV format:
  - First 4 rows are metadata headers (skip them)
  - Row 5 (index 4) is the column header row: "remove", "", "map", ... "Jan 2009", "Feb 2009" ...
  - Data rows start at row 6 (index 5)
  - Each row: col 0 = country/region label, col 5 = EIA source key, cols 6+ = monthly values
  - Months are "Mon YYYY" format

Usage (from repo root):
    python -m research.build_training_dataset
    -- or --
    cd research && python build_training_dataset.py
"""

import csv
import json
import pathlib
import sys
from datetime import datetime, timedelta, date

RESEARCH_DIR    = pathlib.Path(__file__).parent
EVENTS_PATH     = RESEARCH_DIR / "known_disruption_events.json"
BRENT_PATH      = RESEARCH_DIR / "brent_prices.csv.csv"
EIA_PATH        = RESEARCH_DIR / "eia_production.csv.csv"
OUTPUT_PATH     = RESEARCH_DIR / "historical_disruptions.json"


# =============================================================================
# BRENT PRICE LOADER
# Reads daily Brent prices into a dict: date -> price (float)
# Format: "MM/DD/YYYY","Price",...
# =============================================================================

def load_brent_prices(path: pathlib.Path) -> dict[date, float]:
    """
    Returns a dict mapping calendar date → closing Brent price (USD/bbl).
    Dates in the CSV are "MM/DD/YYYY" format.
    Note: file may have UTF-8 BOM; opened with utf-8-sig to strip it.
    """
    prices: dict[date, float] = {}
    with open(path, encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        # Strip any remaining quotes from field names
        reader.fieldnames = [f.strip().strip('"') for f in reader.fieldnames] if reader.fieldnames else reader.fieldnames
        for row in reader:
            raw_date  = row.get("Date", "").strip().strip('"')
            raw_price = row.get("Price", "").strip().strip('"').replace(",", "")
            try:
                d = datetime.strptime(raw_date, "%m/%d/%Y").date()
                p = float(raw_price)
                prices[d] = p
            except (ValueError, KeyError):
                continue
    return prices


def lookup_brent_price(prices: dict[date, float], target: date, window_days: int = 7) -> float | None:
    """
    Find the nearest available Brent price within ±window_days of target.
    Returns None if nothing found in range (trading day gaps, weekends, holidays).
    """
    for delta in range(0, window_days + 1):
        for sign in (0, 1, -1):
            d = target + timedelta(days=delta * sign if delta > 0 else 0)
            if d in prices:
                return prices[d]
            if sign != 0:
                d2 = target + timedelta(days=delta * sign)
                if d2 in prices:
                    return prices[d2]
    return None


# =============================================================================
# EIA PRODUCTION LOADER
# Reads the wide-format EIA CSV into a dict:
#   producer_label -> {"Jan 2009": 9.88, "Feb 2009": 9.86, ...}
# =============================================================================

def load_eia_production(path: pathlib.Path) -> tuple[dict[str, dict[str, float]], list[str]]:
    """
    Returns:
      (producer_data, month_headers)
        producer_data:  {producer_label: {month_str: value_float}}
        month_headers:  ordered list of "Mon YYYY" strings (Jan 2009 … Jul 2026)
    """
    with open(path, encoding="utf-8") as fh:
        raw_rows = list(csv.reader(fh))

    # Row index 4 (0-indexed) is the header row.
    # The first 6 cols are metadata; cols 6+ are "Jan 2009", "Feb 2009", ...
    header_row   = raw_rows[4]
    month_headers: list[str] = [h.strip().strip('"') for h in header_row[6:] if h.strip().strip('"')]

    producer_data: dict[str, dict[str, float]] = {}

    for row in raw_rows[5:]:
        if len(row) < 7:
            continue
        label = row[0].strip().strip('"')
        if not label or label.startswith("3b.") or label in ("remove",):
            continue

        values_raw = row[6: 6 + len(month_headers)]
        monthly: dict[str, float] = {}
        for month_str, val_str in zip(month_headers, values_raw):
            v = val_str.strip().strip('"')
            if not v or v == "--":
                continue
            try:
                monthly[month_str] = float(v)
            except ValueError:
                continue

        if monthly:
            producer_data[label] = monthly

    return producer_data, month_headers


def month_str_from_date(d: date) -> str:
    """Convert a date to EIA month key, e.g. "Sep 2019"."""
    return d.strftime("%b %Y")


def next_month_str(month_str: str) -> str:
    """Return the next month's key, e.g. "Sep 2019" -> "Oct 2019"."""
    dt = datetime.strptime(month_str, "%b %Y")
    # Advance by ~32 days and normalize to first of month
    next_dt = (dt.replace(day=28) + timedelta(days=4)).replace(day=1)
    return next_dt.strftime("%b %Y")


def lookup_volume(producer_data: dict, producer: str, month_str: str) -> float | None:
    """Look up EIA production volume for a producer at a given month key."""
    pdata = producer_data.get(producer)
    if pdata is None:
        return None
    return pdata.get(month_str)


# =============================================================================
# MAIN BUILD FUNCTION
# =============================================================================

def build_dataset() -> list[dict]:
    print("=" * 70)
    print("  Building Historical Disruption Training Dataset")
    print("=" * 70)

    # Load inputs
    print(f"\n  Loading events from {EVENTS_PATH.name}...")
    with open(EVENTS_PATH, encoding="utf-8") as fh:
        events: list[dict] = json.load(fh)
    print(f"  Loaded {len(events)} disruption events.")

    print(f"  Loading Brent prices from {BRENT_PATH.name}...")
    brent = load_brent_prices(BRENT_PATH)
    print(f"  Loaded {len(brent)} daily Brent price records "
          f"({min(brent.keys())} → {max(brent.keys())}).")

    print(f"  Loading EIA production from {EIA_PATH.name}...")
    eia_data, month_headers = load_eia_production(EIA_PATH)
    print(f"  Loaded {len(eia_data)} EIA producer rows, "
          f"{len(month_headers)} months ({month_headers[0]} → {month_headers[-1]}).\n")

    # Show available EIA producers
    print("  EIA producers available:")
    for p in sorted(eia_data.keys()):
        print(f"    - {p}")
    print()

    # Process events
    results: list[dict] = []

    for evt in events:
        event_name        = evt["event"]
        event_date_str    = evt["date"]
        affected_producer = evt["affected_producer"]
        impact_pct        = evt["impact_estimate_pct"]
        source            = evt["source"]

        event_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
        date_30d   = event_date + timedelta(days=30)

        # --- Brent price lookup ---
        price_at_event = lookup_brent_price(brent, event_date)
        price_30d      = lookup_brent_price(brent, date_30d)

        if price_at_event is not None and price_30d is not None:
            price_change_pct = round((price_30d - price_at_event) / price_at_event * 100, 2)
        else:
            price_change_pct = None

        # --- EIA volume lookup ---
        event_month   = month_str_from_date(event_date)
        next_month    = next_month_str(event_month)

        vol_at_event  = lookup_volume(eia_data, affected_producer, event_month)
        vol_after     = lookup_volume(eia_data, affected_producer, next_month)

        if vol_at_event is not None and vol_after is not None and vol_at_event > 0:
            volume_change_pct = round((vol_after - vol_at_event) / vol_at_event * 100, 2)
        else:
            volume_change_pct = None

        # --- Data quality ---
        has_price  = price_change_pct is not None
        has_volume = volume_change_pct is not None

        if has_price and has_volume:
            data_quality = "complete"
        elif has_price or has_volume:
            data_quality = "partial"
        else:
            data_quality = "no_data"

        row = {
            "event":                    event_name,
            "date":                     event_date_str,
            "affected_producer":        affected_producer,
            "signal_severity_estimate": round(impact_pct / 100.0, 2),
            "actual_price_impact_pct":  price_change_pct,
            "actual_volume_impact_pct": volume_change_pct,
            "data_quality":             data_quality,
            "source":                   source,
        }
        results.append(row)

    return results


def print_summary_table(results: list[dict]) -> None:
    """Print the formatted summary table and data quality counts."""
    # Column widths
    ev_w  = 42
    dt_w  = 10
    pr_w  = 18
    imp_w = 8
    p_w   = 12
    v_w   = 12
    q_w   = 8

    header = (
        f"  {'Event':<{ev_w}}  {'Date':<{dt_w}}  {'Producer':<{pr_w}}  "
        f"{'Est%':>{imp_w}}  {'PriceChg%':>{p_w}}  {'VolChg%':>{v_w}}  {'Quality':<{q_w}}"
    )
    divider = "  " + "-" * (ev_w + dt_w + pr_w + imp_w + p_w + v_w + q_w + 14)

    print("=" * 70)
    print("  SUMMARY TABLE — All Events")
    print("=" * 70)
    print(header)
    print(divider)

    counts = {"complete": 0, "partial": 0, "no_data": 0}

    for r in results:
        evt_trunc = r["event"][:ev_w]
        prod_trunc = r["affected_producer"][:pr_w]
        price_str  = f"{r['actual_price_impact_pct']:+.1f}%" if r["actual_price_impact_pct"] is not None else "N/A"
        vol_str    = f"{r['actual_volume_impact_pct']:+.1f}%" if r["actual_volume_impact_pct"] is not None else "N/A"
        counts[r["data_quality"]] += 1

        print(
            f"  {evt_trunc:<{ev_w}}  {r['date']:<{dt_w}}  {prod_trunc:<{pr_w}}  "
            f"{r['signal_severity_estimate']*100:>{imp_w}.0f}  "
            f"{price_str:>{p_w}}  {vol_str:>{v_w}}  {r['data_quality']:<{q_w}}"
        )

    print(divider)
    print()
    print("  DATA QUALITY SUMMARY:")
    print(f"    Complete (price + volume) : {counts['complete']}")
    print(f"    Partial  (one of two)     : {counts['partial']}")
    print(f"    No data                   : {counts['no_data']}")
    print(f"    Total events              : {len(results)}")
    print()


def main() -> None:
    results = build_dataset()

    print_summary_table(results)

    # Write output
    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    print(f"  Output written to: {OUTPUT_PATH}")
    print()


if __name__ == "__main__":
    main()
