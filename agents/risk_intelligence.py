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
    4. explanation = Gemini 1.5 Flash narrative (with try/except fallback to
       a template string — pipeline never crashes on LLM failure).

No ML model. No black-box. All knobs are named constants at the top of this file.
"""

import os
import uuid
import math
import logging
import pathlib
from datetime import datetime, timezone

from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load .env from repo root so GEMINI_API_KEY is available at module import time.
# dotenv is idempotent — safe to call multiple times.
_env_path = pathlib.Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)

logger = logging.getLogger(__name__)


# =============================================================================
# WEIGHT CONSTANTS — change these to tune the formula; do not bury values in code
# =============================================================================

# Per-signal-type credibility/impact weights (used as relative weights, not probs).
#
# Justification:
#   sanctions (0.40) — OFAC SDN listings are legally binding, binary disruption
#                      events, and the strongest leading indicator of supply stops.
#   news      (0.30) — RSS/news signals capture geopolitical intent early;
#                      second-highest weight despite higher noise.
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
CONFIDENCE_FULL_SIGNAL_COUNT: int = 5

# Recency window — signals older than this many hours are penalised in confidence.
RECENCY_WINDOW_HOURS: int = 24

# Recency penalty floor — even fully-stale signals retain this fraction of confidence.
RECENCY_FLOOR: float = 0.30

# Gemini model name — gemini-3.5-flash as requested.
GEMINI_MODEL_NAME: str = "gemini-3.5-flash"


# =============================================================================
# GEMINI LLM SETUP
# =============================================================================

def _init_gemini() -> genai.Client | None:
    """
    Initialise the Gemini client from GEMINI_API_KEY env var.
    Returns None (and logs a warning) if the key is missing — the pipeline
    then falls back to the template explanation without crashing.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning(
            "[Stage3] GEMINI_API_KEY not set — LLM explanations disabled. "
            "Set it in .env to enable Gemini narratives."
        )
        return None
    return genai.Client(api_key=api_key)


# Module-level singleton — initialised once on import.
_gemini_client: genai.Client | None = _init_gemini()


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
    2. Recency factor = average recency score across signals.

    confidence = volume_factor * recency_factor
    """
    n = len(signals)
    if n == 0:
        return 0.0

    volume_factor = min(1.0, n / CONFIDENCE_FULL_SIGNAL_COUNT)

    now = datetime.now(timezone.utc)
    recency_scores: list[float] = []
    for sig in signals:
        # processed_signals uses 'generated_at' as the timestamp field
        ts_str = sig.get("generated_at", sig.get("timestamp", ""))
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            age_hours = (now - ts).total_seconds() / 3600.0
            if age_hours <= RECENCY_WINDOW_HOURS:
                recency_scores.append(1.0)
            else:
                excess = age_hours - RECENCY_WINDOW_HOURS
                decay  = excess / RECENCY_WINDOW_HOURS
                score  = RECENCY_FLOOR + (1.0 - RECENCY_FLOOR) * math.exp(-decay)
                recency_scores.append(round(score, 4))
        except (ValueError, TypeError):
            recency_scores.append(RECENCY_FLOOR)

    recency_factor = sum(recency_scores) / len(recency_scores)
    return round(volume_factor * recency_factor, 4)


# =============================================================================
# LLM EXPLANATION
# =============================================================================

def get_risk_explanation(
    corridor: str,
    risk_score: float,
    contributing_signals: list[dict],
    n_signals: int,
) -> str:
    """
    Call Gemini to produce a 2-3 sentence plain-English explanation of the risk score.

    Falls back to a template string if GEMINI_API_KEY is missing or any API
    error occurs (rate limit, quota, network). Pipeline NEVER crashes on LLM failure.
    """
    if _gemini_client is None:
        return _fallback_explanation(corridor, risk_score, n_signals)

    signal_summaries = "\n".join(
        f"- [{s.get('signal_type', 'unknown')}] {s.get('text_summary', '')}"
        for s in contributing_signals
    )
    prompt = (
        f"You are a supply chain risk analyst. Given the following signals "
        f"for the {corridor} corridor, write a 2-3 sentence explanation of why "
        f"the risk score is {risk_score:.2f} (on a 0-1 scale where 1.0 = certain "
        f"disruption). Be specific and reference the actual signals below. "
        f"Do not invent facts not present in the signals.\n\n"
        f"Signals:\n{signal_summaries}"
    )

    try:
        response = _gemini_client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=prompt,
        )
        text = response.text.strip()
        logger.info("[Stage3] Gemini explanation generated for corridor='%s'.", corridor)
        return text
    except Exception as exc:
        logger.warning(
            "[Stage3] Gemini call failed for corridor='%s': %s. Using fallback.",
            corridor, exc,
        )
        return (
            f"Risk score {risk_score:.2f} for {corridor} based on "
            f"{n_signals} signal(s). (LLM unavailable: {exc})"
        )


def _fallback_explanation(corridor: str, risk_score: float, n_signals: int) -> str:
    """Template explanation used when LLM is disabled or fails."""
    return (
        f"Risk score {risk_score:.2f} for {corridor} corridor based on "
        f"{n_signals} signal(s) "
        f"(sanctions weight={SIGNAL_TYPE_WEIGHTS['sanctions']}, "
        f"news weight={SIGNAL_TYPE_WEIGHTS['news']}, "
        f"shipping weight={SIGNAL_TYPE_WEIGHTS['shipping']}, "
        f"price weight={SIGNAL_TYPE_WEIGHTS['price']}). "
        f"Confidence reflects signal volume and recency. "
        f"[LLM explanation disabled — set GEMINI_API_KEY in .env to enable]"
    )


# =============================================================================
# PUBLIC API
# =============================================================================

def compute_risk_score(signals: list[dict], use_llm: bool = True) -> dict:
    """
    Compute a risk_scores row (§5 Stage 3 schema) for ONE corridor.

    Args:
        signals: list of processed_signal dicts for a single corridor.
                 All must share the same 'corridor' value.
        use_llm: If True (default), calls Gemini to generate the explanation.
                 Set False to skip the LLM call for fast/offline testing.

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
            "source":               "real",
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

    corridor   = corridors.pop()
    risk_score = _weighted_risk_score(signals)
    confidence = _compute_confidence(signals)
    signal_ids = [s["id"] for s in signals if "id" in s]
    n          = len(signals)

    if use_llm:
        explanation = get_risk_explanation(corridor, risk_score, signals, n)
    else:
        explanation = _fallback_explanation(corridor, risk_score, n)

    return {
        "id":                   str(uuid.uuid4()),
        "corridor":             corridor,
        "supplier":             None,
        "risk_score":           risk_score,
        "confidence":           confidence,
        "explanation":          explanation,
        "contributing_signals": signal_ids,
        "source":               "real",      # live Supabase data — not mock
        "generated_at":         datetime.now(timezone.utc).isoformat(),
    }
