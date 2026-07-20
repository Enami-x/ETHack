"""
/agents/ingest_eia.py
=====================
Stage 1 — Data Collection: EIA (U.S. Energy Information Administration) ingester

Responsibility:
    Fetch live daily crude oil spot prices (Brent + WTI) and weekly petroleum
    supply/inventory data from the EIA API v2, then return:
      1. raw_signal rows (for the pipeline — source="eia")
      2. A structured CrudeOilSnapshot dict for direct dashboard display

EIA API v2 docs: https://www.eia.gov/opendata/
API key: set EIA_API_KEY in .env

Series used:
    RBRTE  — Europe Brent Spot Price FOB ($/barrel), daily
    RWTC   — WTI Cushing Spot Price FOB ($/barrel), daily
    WTTSTUS — US crude oil in storage (weekly, thousand barrels)
    WCRFPUS — US crude oil refinery inputs (weekly, thousand barrels/day)
"""

import os
import uuid
import logging
import pathlib
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from dotenv import load_dotenv

# Load .env from repo root
_env_path = pathlib.Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

EIA_BASE = "https://api.eia.gov/v2"

# Series IDs for the EIA API v2 petroleum spot prices endpoint
PRICE_SERIES = {
    "brent": {
        "product": "EPCBRENT",  # UK Brent Crude
        "series":  "RBRTE",
        "label":   "Brent Crude FOB ($/bbl)",
    },
    "wti": {
        "product": "EPCWTI",    # WTI Cushing
        "series":  "RWTC",
        "label":   "WTI Cushing FOB ($/bbl)",
    },
}

# Cache settings
CACHE_DIR  = pathlib.Path(__file__).parent.parent / "cache"
CACHE_TTL_MINUTES = 60   # price data: refresh every hour

REQUEST_TIMEOUT = 15     # seconds


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_api_key() -> Optional[str]:
    key = os.getenv("EIA_API_KEY", "").strip()
    if not key:
        logger.warning("[EIA] EIA_API_KEY not set — add it to .env")
    return key or None


def _cache_path(name: str) -> pathlib.Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"eia_{name}.json"


def _cache_is_fresh(path: pathlib.Path, ttl_minutes: int = CACHE_TTL_MINUTES) -> bool:
    if not path.exists():
        return False
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(
        path.stat().st_mtime, tz=timezone.utc
    )
    return age < timedelta(minutes=ttl_minutes)


def _eia_get(path: str, params: dict) -> Optional[dict]:
    """Generic EIA API v2 GET with error handling."""
    api_key = _get_api_key()
    if not api_key:
        return None
    params["api_key"] = api_key
    url = f"{EIA_BASE}{path}"
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        logger.error("[EIA] Request timed out: %s", url)
    except requests.exceptions.HTTPError as exc:
        logger.error("[EIA] HTTP %s: %s", exc.response.status_code, url)
    except Exception as exc:
        logger.error("[EIA] Unexpected error: %s", exc)
    return None


# ── Fetch spot prices ─────────────────────────────────────────────────────────

def fetch_crude_prices(days: int = 30) -> dict:
    """
    Fetch Brent and WTI daily spot prices for the last `days` days.

    Returns:
        {
          "brent": [{"date": "YYYY-MM-DD", "price": float}, ...],   # newest first
          "wti":   [...],
          "fetched_at": "ISO8601",
          "source": "eia_live" | "eia_cache" | "eia_unavailable"
        }
    """
    import json

    cache = _cache_path("prices")
    if _cache_is_fresh(cache):
        try:
            data = json.loads(cache.read_text())
            data["source"] = "eia_cache"
            logger.info("[EIA] Loaded price data from cache.")
            return data
        except Exception:
            pass

    result = {"brent": [], "wti": [], "fetched_at": datetime.now(timezone.utc).isoformat()}

    for name, meta in PRICE_SERIES.items():
        payload = _eia_get(
            "/petroleum/pri/spt/data/",
            {
                "frequency":         "daily",
                "data[0]":           "value",
                "facets[product][]": meta["product"],
                "sort[0][column]":   "period",
                "sort[0][direction]":"desc",
                "length":            str(days),
            }
        )
        if not payload:
            logger.warning("[EIA] Could not fetch %s prices.", name)
            continue

        rows = payload.get("response", {}).get("data", [])
        prices = []
        for row in rows:
            try:
                prices.append({
                    "date":  row["period"],
                    "price": float(row["value"]) if row["value"] not in (None, "") else None,
                })
            except (KeyError, TypeError, ValueError):
                continue

        result[name] = prices
        logger.info("[EIA] Fetched %d %s price points.", len(prices), name.upper())

    if result["brent"] or result["wti"]:
        result["source"] = "eia_live"
        try:
            cache.write_text(json.dumps(result))
        except Exception:
            pass
    else:
        result["source"] = "eia_unavailable"

    return result


# ── Fetch inventory / supply data ─────────────────────────────────────────────

def fetch_supply_data() -> dict:
    """
    Fetch weekly US crude oil inventory and refinery input data.

    Returns:
        {
          "inventory_kb":       float | None,   # thousand barrels in storage
          "refinery_inputs_kbd": float | None,  # thousand bbl/day refinery runs
          "inventory_trend":    "building" | "drawing" | "stable" | None,
          "fetched_at":         "ISO8601",
          "source":             "eia_live" | "eia_cache" | "eia_unavailable"
        }
    """
    import json

    cache = _cache_path("supply")
    if _cache_is_fresh(cache, ttl_minutes=360):   # Weekly data — cache for 6h
        try:
            data = json.loads(cache.read_text())
            data["source"] = "eia_cache"
            return data
        except Exception:
            pass

    result = {
        "inventory_kb": None,
        "refinery_inputs_kbd": None,
        "inventory_trend": None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "eia_unavailable",
    }

    # Weekly crude stocks — WTTSTUS
    inv_payload = _eia_get(
        "/petroleum/stoc/wstk/data/",
        {
            "frequency":            "weekly",
            "data[0]":              "value",
            "facets[product][]":    "EPC0",   # Crude oil
            "facets[duoarea][]":    "NUS",    # Total US
            "facets[process][]":    "SAE",    # Ending stocks
            "sort[0][column]":      "period",
            "sort[0][direction]":   "desc",
            "length":               "4",      # Last 4 weeks
        }
    )

    if inv_payload:
        rows = inv_payload.get("response", {}).get("data", [])
        if rows:
            try:
                result["inventory_kb"] = float(rows[0]["value"])
                if len(rows) >= 2 and rows[1]["value"] not in (None, ""):
                    prev = float(rows[1]["value"])
                    curr = result["inventory_kb"]
                    diff_pct = (curr - prev) / prev if prev else 0
                    result["inventory_trend"] = (
                        "building" if diff_pct > 0.005
                        else "drawing" if diff_pct < -0.005
                        else "stable"
                    )
            except (IndexError, TypeError, ValueError, KeyError):
                pass

    # Refinery inputs — WCRFPUS
    ref_payload = _eia_get(
        "/petroleum/cons/psup/data/",
        {
            "frequency":            "weekly",
            "data[0]":              "value",
            "facets[duoarea][]":    "NUS",
            "facets[product][]":    "EPC0",
            "facets[process][]":    "YIR",   # Refinery inputs
            "sort[0][column]":      "period",
            "sort[0][direction]":   "desc",
            "length":               "1",
        }
    )

    if ref_payload:
        rows = ref_payload.get("response", {}).get("data", [])
        if rows:
            try:
                result["refinery_inputs_kbd"] = float(rows[0]["value"])
            except (IndexError, TypeError, ValueError, KeyError):
                pass

    if result["inventory_kb"] is not None or result["refinery_inputs_kbd"] is not None:
        result["source"] = "eia_live"
        try:
            cache.write_text(json.dumps(result))
        except Exception:
            pass

    return result


# ── Build price-based raw_signals ─────────────────────────────────────────────

def build_price_signal(prices: dict) -> list[dict]:
    """
    Convert EIA price data into raw_signal rows for the pipeline.

    Signals are generated per corridor (hormuz, red_sea) with a severity_hint
    derived from the 7-day price change: large price spikes → higher severity.

    Returns list of raw_signal dicts matching §5 Stage 1 schema.
    """
    signals = []
    brent = prices.get("brent", [])
    if len(brent) < 2:
        logger.warning("[EIA] Not enough Brent data to compute price signal.")
        return signals

    # Latest and 7-days-ago price
    latest_price = brent[0].get("price")
    price_7d_ago = next((p["price"] for p in brent[7:8]), None)

    if latest_price is None:
        return signals

    # Compute price signal severity: 0=no move, 1=+20% spike
    pct_change = 0.0
    if price_7d_ago and price_7d_ago > 0:
        pct_change = (latest_price - price_7d_ago) / price_7d_ago

    # Normalise: a +20% spike = severity 1.0, a -20% = severity 0.0 (floor at 0)
    severity = max(0.0, min(1.0, 0.5 + pct_change * 2.5))

    # Emit one price signal per corridor (price moves affect all corridors equally)
    for corridor in ["hormuz", "red_sea"]:
        signals.append({
            "id":        str(uuid.uuid4()),
            "source":    "eia",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "corridor":  corridor,
            "raw_payload": {
                "brent_usd":     latest_price,
                "brent_7d_ago":  price_7d_ago,
                "pct_change_7d": round(pct_change * 100, 2),
                "severity_computed": round(severity, 3),
                "series":        "RBRTE",
                "date":          brent[0].get("date"),
            },
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        })

    logger.info(
        "[EIA] Price signal: Brent $%.2f, 7d change: %.1f%%, severity=%.3f",
        latest_price, pct_change * 100, severity
    )
    return signals


# ── Public entry point ────────────────────────────────────────────────────────

def fetch_eia_signals() -> tuple[list[dict], dict]:
    """
    Main pipeline entry point — fetches prices + supply data.

    Returns:
        (raw_signals, snapshot)

        raw_signals — list of raw_signal dicts for the pipeline
        snapshot    — dict with all EIA data for the dashboard CrudeOilPanel
    """
    prices   = fetch_crude_prices(days=30)
    supply   = fetch_supply_data()
    signals  = build_price_signal(prices)

    # Latest Brent and WTI for snapshot
    brent_list = prices.get("brent", [])
    wti_list   = prices.get("wti", [])
    latest_brent = brent_list[0]["price"] if brent_list else None
    latest_wti   = wti_list[0]["price"]   if wti_list   else None

    prev_brent = brent_list[1]["price"] if len(brent_list) > 1 else None
    prev_wti   = wti_list[1]["price"]   if len(wti_list)  > 1 else None

    def _pct(curr, prev):
        if curr and prev and prev != 0:
            return round((curr - prev) / prev * 100, 2)
        return None

    snapshot = {
        "brent_usd":          latest_brent,
        "brent_prev_usd":     prev_brent,
        "brent_pct_change":   _pct(latest_brent, prev_brent),
        "brent_series":       brent_list,           # [{date, price}, ...]
        "wti_usd":            latest_wti,
        "wti_prev_usd":       prev_wti,
        "wti_pct_change":     _pct(latest_wti, prev_wti),
        "wti_series":         wti_list,
        "inventory_kb":       supply.get("inventory_kb"),
        "refinery_inputs_kbd":supply.get("refinery_inputs_kbd"),
        "inventory_trend":    supply.get("inventory_trend"),
        "data_source":        prices.get("source"),
        "fetched_at":         prices.get("fetched_at"),
    }

    logger.info(
        "[EIA] Snapshot — Brent: $%s | WTI: $%s | Inventory: %s kb | Source: %s",
        latest_brent, latest_wti, supply.get("inventory_kb"), prices.get("source")
    )
    return signals, snapshot
