"""
/agents/normalize_signals.py
=============================
Stage 2 — Data Processing

Responsibility:
    Transform raw_signals (Stage 1 output) into a standardised processed_signals
    shape matching the §5 Stage 2 schema in ARCHITECTURE.md.

    Two source types handled:
      - source="rss"  → signal_type="news",       one row per article
      - source="ofac" → signal_type="sanctions",  ONE aggregated row per corridor

    See module-level constants for keyword lists and the OFAC severity formula.
"""

import uuid
import logging
from collections import defaultdict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION CONSTANTS — tune these without touching normalisation logic
# =============================================================================

# RSS severity scoring — keyword sets are checked against title + summary combined.
# If any HIGH keyword present  → severity_hint = HIGH_SEVERITY_SCORE
# Else if any MEDIUM keyword   → severity_hint = MEDIUM_SEVERITY_SCORE
# Else                         → severity_hint = LOW_SEVERITY_SCORE
HIGH_SEVERITY_KEYWORDS: list[str] = [
    "attack", "attacked", "attacking",
    "seized", "seize", "seizure",
    "halt", "halted", "halts",
    "blocked", "blocking", "blockade",
    "strike", "struck", "strikes",
    "destroyed", "destruction",
    "explosion", "exploded",
    "missile", "drone strike",
    "closed", "closure",
]

MEDIUM_SEVERITY_KEYWORDS: list[str] = [
    "warns", "warning",
    "risk", "risky",
    "threat", "threatens",
    "disruption", "disrupts",
    "escalation", "escalating", "escalate",
    "tension", "tensions",
    "conflict",
    "sanctions", "sanctioned",
    "detained",
    "incident",
]

HIGH_SEVERITY_SCORE:   float = 0.8
MEDIUM_SEVERITY_SCORE: float = 0.5
LOW_SEVERITY_SCORE:    float = 0.3

# OFAC severity formula — background risk floor from sanctions count per corridor.
# Formula:  severity_hint = min(count / OFAC_SEVERITY_DIVISOR, OFAC_SEVERITY_CAP)
#
# Rationale: 1000 active Iran petroleum/shipping sanctions → 1.0 raw score, but we
# cap at OFAC_SEVERITY_CAP (0.4) so the background OFAC signal never drowns out
# real-time RSS news signals (which can reach 0.8 for active attacks).
# Example: 1088 entries → min(1088/1000, 0.4) = min(1.088, 0.4) = 0.40
OFAC_SEVERITY_DIVISOR: float = 1000.0
OFAC_SEVERITY_CAP:     float = 0.40

# Valid corridor values (must match §5 schema)
VALID_CORRIDORS = {"hormuz", "red_sea", "suez", "other"}


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _rss_severity(title: str, summary: str) -> float:
    """
    Compute severity_hint for an RSS news signal.
    Searches combined title+summary for HIGH then MEDIUM keywords (case-insensitive).
    Returns HIGH_SEVERITY_SCORE, MEDIUM_SEVERITY_SCORE, or LOW_SEVERITY_SCORE.
    """
    text = (title + " " + summary).lower()
    if any(kw in text for kw in HIGH_SEVERITY_KEYWORDS):
        return HIGH_SEVERITY_SCORE
    if any(kw in text for kw in MEDIUM_SEVERITY_KEYWORDS):
        return MEDIUM_SEVERITY_SCORE
    return LOW_SEVERITY_SCORE


def _normalize_rss(raw: dict) -> dict:
    """Convert a single RSS raw_signal to a processed_signals row."""
    payload  = raw.get("raw_payload", {})
    title    = payload.get("title", "")
    summary  = payload.get("summary", "")
    corridor = raw.get("corridor", "other")

    return {
        "id":                   str(uuid.uuid4()),
        "corridor":             corridor,
        "signal_type":          "news",
        "severity_hint":        _rss_severity(title, summary),
        "text_summary":         title or summary[:200],
        "contributing_signals": [raw.get("id", "")],
        "source":               "real",
        "generated_at":         datetime.now(timezone.utc).isoformat(),
    }


def _normalize_ofac_group(corridor: str, entries: list[dict]) -> dict:
    """
    Collapse all OFAC entries for one corridor into a single aggregated signal.

    severity_hint formula:
        min(count / OFAC_SEVERITY_DIVISOR, OFAC_SEVERITY_CAP)
    See module constants for rationale.
    """
    count = len(entries)
    severity = min(count / OFAC_SEVERITY_DIVISOR, OFAC_SEVERITY_CAP)

    return {
        "id":          str(uuid.uuid4()),
        "corridor":    corridor,
        "signal_type": "sanctions",
        "severity_hint": round(severity, 4),
        "text_summary":  (
            f"{count} active Iran petroleum/shipping sanctions entries for {corridor}"
        ),
        # Store all contributing raw_signal IDs for traceability
        "contributing_signals": [e.get("id", "") for e in entries],
        "source":       "real",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _normalize_eia(raw: dict) -> dict:
    """
    Convert a single EIA price raw_signal to a processed_signals row.

    signal_type = "price"  (weight 0.10 in risk formula — confirming, not leading)
    severity_hint = pre-computed price momentum from ingest_eia.py
    """
    payload  = raw.get("raw_payload", {})
    severity = payload.get("severity_computed", 0.5)
    brent    = payload.get("brent_usd", "?")
    pct      = payload.get("pct_change_7d", 0.0)
    corridor = raw.get("corridor", "other")
    date     = payload.get("date", "")

    return {
        "id":                   str(uuid.uuid4()),
        "corridor":             corridor,
        "signal_type":          "price",
        "severity_hint":        round(float(severity), 4),
        "text_summary":         (
            f"Brent crude ${brent}/bbl on {date} "
            f"({'+'if pct>=0 else ''}{pct:.1f}% vs 7 days ago)"
        ),
        "contributing_signals": [raw.get("id", "")],
        "source":               "real",
        "generated_at":         datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# PUBLIC API
# =============================================================================

def normalize_signals(raw_signals: list[dict]) -> list[dict]:
    """
    Transform Stage 1 raw_signals into Stage 2 processed_signals.

    Processing rules:
      - RSS  (source="rss"):  one processed row per article, signal_type="news"
      - OFAC (source="ofac"): grouped by corridor → ONE aggregated row per corridor,
                              signal_type="sanctions"
      - Unknown sources: logged and skipped.

    Args:
        raw_signals: list of raw_signal dicts matching §5 Stage 1 schema.

    Returns:
        list of processed_signal dicts matching §5 Stage 2 schema.
    """
    processed: list[dict] = []
    ofac_by_corridor: dict[str, list[dict]] = defaultdict(list)

    rss_count  = 0
    ofac_count = 0
    skipped    = 0

    for raw in raw_signals:
        source = raw.get("source", "")

        if source == "rss":
            processed.append(_normalize_rss(raw))
            rss_count += 1

        elif source == "ofac":
            corridor = raw.get("corridor", "other")
            ofac_by_corridor[corridor].append(raw)
            ofac_count += 1

        elif source == "eia":
            processed.append(_normalize_eia(raw))

        else:
            logger.debug("[normalize] Unknown source '%s' — skipping.", source)
            skipped += 1

    # Aggregate OFAC groups — one signal per corridor
    for corridor, entries in ofac_by_corridor.items():
        processed.append(_normalize_ofac_group(corridor, entries))

    logger.info(
        "[normalize] %d raw signals in → %d RSS news + %d OFAC entries "
        "(collapsed to %d corridor aggregate(s)) + %d skipped → %d processed signals out.",
        len(raw_signals),
        rss_count,
        ofac_count,
        len(ofac_by_corridor),
        skipped,
        len(processed),
    )
    return processed
