"""
/agents/risk_intelligence.py
============================
Stage 3 — Risk Intelligence Agent

Responsibility:
    Compute a live disruption-probability risk score per corridor from a list of
    processed_signal rows (Stage 2 output), producing a risk_scores row that matches
    the §5 Stage 3 schema in ARCHITECTURE.md exactly.

Formula (transparent, inspectable, demo-safe):
    1. For each signal, its contribution = SIGNAL_TYPE_WEIGHT[signal_type] * severity_hint
    2. risk_score = sum(contributions) / sum(weights used)
       i.e. a weighted average of severity_hint, where each signal is weighted
       by the credibility/impact of its source type.
    3. confidence = f(signal_count, recency) — see _compute_confidence() below.

No ML model. No black-box. All knobs are named constants at the top of this file.
"""

import uuid
import math
from datetime import datetime, timezone, timedelta


# =============================================================================
# WEIGHT CONSTANTS — change these to tune the formula; do not bury values in code
# =============================================================================

# Per-signal-type credibility/impact weights (must sum to <= 1 individually;
# they are used as relative weights, not probabilities).
#
# Justification:
#   sanctions (0.40) — OFAC SDN listings are legally binding, binary disruption
#                      events, and the strongest leading indicator of supply stops.
#   news      (0.30) — GDELT/news signals are high-volume but noisy; second-highest
#                      weight because they capture geopolitical intent early.
#   shipping  (0.20) — AIS vessel data is objective but lagging (ships already
#                      diverted before signal fires); good confirming signal.
#   price     (0.10) — Price moves are consequences of disruption, not causes.
#                      Used as a weak confirming signal to avoid double-counting.
SIGNAL_TYPE_WEIGHTS: dict[str, float] = {
    "sanctions": 0.40,
    "news":      0.30,
    "shipping":  0.20,
    "price":     0.10,
}

# Confidence scaling — how many signals constitute a "fully confident" reading.
# Below this threshold, confidence is scaled down proportionally.
CONFIDENCE_FULL_SIGNAL_COUNT: int = 5

# Recency window — signals older than this many hours are penalised in confidence.
RECENCY_WINDOW_HOURS: int = 24

# Recency penalty floor — even fully-stale signals retain this fraction of their
# confidence contribution (avoids zeroing out lone-signal corridors entirely).
RECENCY_FLOOR: float = 0.30


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _weighted_risk_score(signals: list[dict]) -> float:
    """
    Weighted-average risk score across all signals for a corridor.

    Formula:
        score = SUM(w_i * s_i) / SUM(w_i)
        where w_i = SIGNAL_TYPE_WEIGHTS[signal_type_i]
              s_i = severity_hint_i  (0.0 – 1.0)

    Returns 0.0 if no signals or no recognised signal types.
    """
    numerator   = 0.0
    denominator = 0.0
    for sig in signals:
        stype  = sig.get("signal_type", "")
        weight = SIGNAL_TYPE_WEIGHTS.get(stype, 0.0)
        sev    = float(sig.get("severity_hint", 0.0))
        numerator   += weight * sev
        denominator += weight
    if denominator == 0.0:
        return 0.0
    return round(numerator / denominator, 4)


def _compute_confidence(signals: list[dict]) -> float:
    """
    Confidence in the risk_score based on two factors:

    1. Volume factor  = min(1.0, n / CONFIDENCE_FULL_SIGNAL_COUNT)
       More signals → more confidence, capped at 1.0 at CONFIDENCE_FULL_SIGNAL_COUNT.

    2. Recency factor = average recency score across signals, where each signal's
       recency score is:
           1.0  if age <= RECENCY_WINDOW_HOURS
           RECENCY_FLOOR + (1 - RECENCY_FLOOR) * exp(-decay)  if older,
           decaying toward RECENCY_FLOOR for very old signals.

    confidence = volume_factor * recency_factor
    """
    n = len(signals)
    if n == 0:
        return 0.0

    volume_factor = min(1.0, n / CONFIDENCE_FULL_SIGNAL_COUNT)

    now = datetime.now(timezone.utc)
    recency_scores: list[float] = []
    for sig in signals:
        ts_str = sig.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            age_hours = (now - ts).total_seconds() / 3600.0
            if age_hours <= RECENCY_WINDOW_HOURS:
                recency_scores.append(1.0)
            else:
                # Exponential decay beyond the recency window
                excess = age_hours - RECENCY_WINDOW_HOURS
                decay  = excess / RECENCY_WINDOW_HOURS  # decays by 1/e per extra window
                score  = RECENCY_FLOOR + (1.0 - RECENCY_FLOOR) * math.exp(-decay)
                recency_scores.append(round(score, 4))
        except (ValueError, TypeError):
            recency_scores.append(RECENCY_FLOOR)

    recency_factor = sum(recency_scores) / len(recency_scores)
    return round(volume_factor * recency_factor, 4)


# =============================================================================
# PUBLIC API
# =============================================================================

def compute_risk_score(signals: list[dict]) -> dict:
    """
    Compute a risk_scores row (§5 Stage 3 schema) for ONE corridor.

    Args:
        signals: list of processed_signal dicts for a single corridor.
                 All must share the same 'corridor' value.

    Returns:
        A dict matching the risk_scores schema exactly:
        {
            "id":                   str (uuid4),
            "corridor":             str,
            "supplier":             None,
            "risk_score":           float (0.0 – 1.0),
            "confidence":           float (0.0 – 1.0),
            "explanation":          str,
            "contributing_signals": list[str],
            "source":               "mock",
            "generated_at":         str (ISO8601),
        }

    Raises:
        ValueError: if signals is empty or corridors are mixed.
    """
    if not signals:
        raise ValueError("compute_risk_score() requires at least one signal.")

    corridors = {s.get("corridor") for s in signals}
    if len(corridors) > 1:
        raise ValueError(
            f"All signals must share the same corridor. Got: {corridors}"
        )

    corridor = corridors.pop()
    risk_score  = _weighted_risk_score(signals)
    confidence  = _compute_confidence(signals)
    signal_ids  = [s["id"] for s in signals if "id" in s]
    n           = len(signals)

    # -------------------------------------------------------------------------
    # TODO: Replace this template string with a Claude Sonnet API call.
    #
    # Suggested prompt:
    #   "You are a geopolitical energy-risk analyst. Given the following
    #    {n} signals for the {corridor} corridor with a computed risk score of
    #    {risk_score:.2f} and confidence {confidence:.2f}, write a 2-sentence
    #    plain-English explanation of the current risk level and the primary
    #    drivers. Signals: {json.dumps(signals, indent=2)}"
    #
    # Replace the line below with the Claude API response text.
    # -------------------------------------------------------------------------
    explanation = (
        f"Risk score {risk_score:.2f} for {corridor} corridor based on "
        f"{n} signal(s) "
        f"(sanctions weight={SIGNAL_TYPE_WEIGHTS['sanctions']}, "
        f"news weight={SIGNAL_TYPE_WEIGHTS['news']}, "
        f"shipping weight={SIGNAL_TYPE_WEIGHTS['shipping']}, "
        f"price weight={SIGNAL_TYPE_WEIGHTS['price']}). "
        f"Confidence {confidence:.2f} reflects signal volume and recency. "
        f"[TODO: replace with Claude Sonnet narrative]"
    )

    return {
        "id":                   str(uuid.uuid4()),
        "corridor":             corridor,
        "supplier":             None,
        "risk_score":           risk_score,
        "confidence":           confidence,
        "explanation":          explanation,
        "contributing_signals": signal_ids,
        "source":               "mock",
        "generated_at":         datetime.now(timezone.utc).isoformat(),
    }
