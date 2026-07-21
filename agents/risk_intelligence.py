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

import uuid
import math
import logging
import pathlib
from datetime import datetime, timezone

from dotenv import load_dotenv

from agents.llm_client import generate_text, LLMUnavailable, llm_status

# Load .env from repo root so LLM keys are available at module import time.
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
#   sanctions (0.40) — OFAC SDN listings are legally binding but SLOW-MOVING and
#                      STRUCTURAL: they describe a persistent baseline regime, not an
#                      acute, leading indicator of imminent corridor closure. As of
#                      Task 2 this weight is RETAINED here for calibration/traceability
#                      only — sanctions no longer enter the acute weighted average.
#                      Instead they set a persistent baseline-risk FLOOR (see
#                      SANCTIONS_FLOOR_SCALE and _sanctions_floor()). This resolves the
#                      old contradiction where sanctions carried the highest weight yet
#                      had severity capped at 0.4 in normalize_signals.py, structurally
#                      limiting their contribution below news.
#   news      (0.30) — RSS/news signals capture geopolitical intent early; the
#                      highest-weighted LEADING (acute) signal despite higher noise.
#   shipping  (0.20) — AIS vessel data is objective but lagging (ships already
#                      diverted before signal fires); good confirming leading signal.
#   price     (0.10) — Price moves are consequences of disruption, not causes.
#                      Used as a weak confirming leading signal to avoid double-counting.
SIGNAL_TYPE_WEIGHTS: dict[str, float] = {
    "sanctions": 0.40,
    "news":      0.30,
    "shipping":  0.20,
    "price":     0.10,
}

# Leading (acute) signal types — these drive the ACUTE risk score via a weighted
# average, renormalised over whichever of them are present (Task 1 + Task 2).
# Sanctions are deliberately EXCLUDED here — they enter as a structural floor below.
LEADING_SIGNAL_TYPES: tuple[str, ...] = ("news", "shipping", "price")

# Structural signal types — slow-moving baseline risk, applied as a floor not a
# weighted leading term.
STRUCTURAL_SIGNAL_TYPES: tuple[str, ...] = ("sanctions",)

# Sanctions floor scaling. The normalized sanctions severity_hint (0.0–0.4, capped
# by OFAC_SEVERITY_CAP in normalize_signals.py) is mapped to a persistent baseline
# risk floor via:  sanctions_floor = min(1.0, sanctions_severity * SANCTIONS_FLOOR_SCALE)
# Scale 1.0 = sanctions severity maps 1:1 to the floor (a heavy sanctions regime with
# no acute signals yields a ~0.4 baseline, never imminent-closure territory). The
# final risk_score = max(acute_score, sanctions_floor): acute leading signals can push
# risk above the floor, but risk never drops below the structural baseline. Tunable.
SANCTIONS_FLOOR_SCALE: float = 1.0

# How to collapse multiple signals of the SAME type into one per-type severity
# before the weighted average. "max" = the single most severe signal of that type
# represents the type (a lone credible attack report must not be diluted by ten
# mild ones). Kept as a named, documented choice — swap to "mean" here if a
# volume-averaged reading is preferred. See _aggregate_severity_by_type().
TYPE_SEVERITY_AGGREGATION: str = "max"

# Confidence scaling — how many signals constitute a "fully confident" reading.
CONFIDENCE_FULL_SIGNAL_COUNT: int = 5

# Recency window — signals older than this many hours are penalised in confidence.
RECENCY_WINDOW_HOURS: int = 24

# Recency penalty floor — even fully-stale signals retain this fraction of confidence.
RECENCY_FLOOR: float = 0.30

# Uncertainty band (Task 3): half-width of the low/high band around risk_score, as a
# fraction of the score, reached at zero confidence. At confidence=1.0 the band
# collapses to the point estimate. Mirrors scenario_modeling.BAND_MAX_HALF_WIDTH_FRAC.
BAND_MAX_HALF_WIDTH_FRAC: float = 0.5

# News event de-duplication (Task 4). Confidence must reflect the number of distinct
# EVENTS, not raw article volume — 15 outlets covering one incident is one event, not
# 15. News signals are clustered by title similarity (Jaccard over word tokens); two
# articles are the "same event" when their similarity >= NEWS_EVENT_SIMILARITY_THRESHOLD.
# (Corridor is already fixed per corridor-scoped call; a time window is not usable here
# because normalize_signals stamps every row with processing-time generated_at, not the
# article publish time — so similarity is the discriminator.)
NEWS_EVENT_SIMILARITY_THRESHOLD: float = 0.5

# Tokens shorter than this or in the stopword set are ignored when comparing titles.
_TITLE_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "as", "at", "by",
    "is", "are", "was", "were", "be", "with", "amid", "over", "after", "from", "its",
    "new", "says", "say", "will", "has", "have", "up", "out",
})


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _aggregate_severity_by_type(signals: list[dict]) -> dict[str, float]:
    """
    Collapse the (possibly many) signals of each type into ONE representative
    severity per type, so that a type with many rows (e.g. 15 news articles) does
    not out-vote a type with a single row (e.g. one sanctions aggregate) purely by
    volume. Aggregation method is TYPE_SEVERITY_AGGREGATION ("max" by default).

    Only recognised signal types (those in SIGNAL_TYPE_WEIGHTS) are returned.
    """
    by_type: dict[str, list[float]] = {}
    for sig in signals:
        stype = sig.get("signal_type", "")
        if stype not in SIGNAL_TYPE_WEIGHTS:
            continue  # unknown/unweighted type — ignore, don't let it skew the mix
        by_type.setdefault(stype, []).append(float(sig.get("severity_hint", 0.0)))

    agg: dict[str, float] = {}
    for stype, sevs in by_type.items():
        if TYPE_SEVERITY_AGGREGATION == "mean":
            agg[stype] = sum(sevs) / len(sevs)
        else:  # "max" (default)
            agg[stype] = max(sevs)
    return agg


def _renormalized_weights(present_types: list[str]) -> dict[str, float]:
    """
    Renormalise SIGNAL_TYPE_WEIGHTS over ONLY the signal types actually present so
    the weights of present types sum to 1.0.

    Why: the static weights (sanctions 0.40, news 0.30, shipping 0.20, price 0.10)
    assume all four types exist. In reality there is NO shipping feed and price can
    be missing during EIA outages. Without renormalisation the absent types' weight
    would be dead mass that structurally caps the maximum achievable score. By
    dividing each present type's weight by the sum of present weights, the score is
    a true weighted average over whatever evidence actually exists for the corridor.
    """
    present_mass = sum(SIGNAL_TYPE_WEIGHTS[t] for t in present_types)
    if present_mass == 0.0:
        return {}
    return {t: SIGNAL_TYPE_WEIGHTS[t] / present_mass for t in present_types}


def _acute_score(type_severity: dict[str, float]) -> float:
    """
    ACUTE risk score = weighted average over the PRESENT *leading* signal types
    (news / shipping / price), with their weights renormalised to sum to 1.0.

    Sanctions are excluded here (structural, handled as a floor). Formula:
        acute = SUM_over_present_leading( w'_t * sev_t )
        where w'_t = SIGNAL_TYPE_WEIGHTS[t] / SUM(present leading weights)
              sev_t = per-type aggregated severity (0.0 – 1.0)

    Returns 0.0 if no leading signal types are present for the corridor.
    """
    present_leading = [t for t in type_severity if t in LEADING_SIGNAL_TYPES]
    if not present_leading:
        return 0.0
    weights = _renormalized_weights(present_leading)
    score = sum(weights[t] * type_severity[t] for t in present_leading)
    return round(score, 4)


def _confidence_band(expected: float, confidence: float) -> dict:
    """
    {low, expected, high} band around a 0–1 risk_score, widening as confidence falls
    (Task 3). half_width = BAND_MAX_HALF_WIDTH_FRAC × (1 − confidence); clamped to [0, 1].
    """
    conf = max(0.0, min(1.0, confidence))
    hw   = BAND_MAX_HALF_WIDTH_FRAC * (1.0 - conf)
    return {
        "low":      round(max(0.0, expected * (1.0 - hw)), 4),
        "expected": round(expected, 4),
        "high":     round(min(1.0, expected * (1.0 + hw)), 4),
    }


def _sanctions_floor(type_severity: dict[str, float]) -> float:
    """
    Structural sanctions FLOOR = normalized sanctions severity × SANCTIONS_FLOOR_SCALE,
    clamped to [0, 1]. Represents persistent baseline corridor risk from the sanctions
    regime, independent of any acute leading signal. 0.0 if no sanctions signal present.
    """
    sev = type_severity.get("sanctions", 0.0)
    return round(min(1.0, sev * SANCTIONS_FLOOR_SCALE), 4)


def _title_tokens(text: str) -> set[str]:
    """Lowercase word tokens for title-similarity, minus stopwords and 1–2 char noise."""
    import re
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _TITLE_STOPWORDS}


def _distinct_news_event_count(news_signals: list[dict]) -> int:
    """
    Cluster news signals into distinct EVENTS by greedy title-similarity (Jaccard over
    word tokens) and return the cluster count. 15 outlets on one incident -> 1 event.
    Empty/token-less titles each count as their own event (can't prove duplication).
    """
    clusters: list[set[str]] = []   # one representative token-set per event cluster
    for sig in news_signals:
        toks = _title_tokens(sig.get("text_summary", ""))
        if not toks:
            clusters.append(set())          # unmergeable — its own event
            continue
        for rep in clusters:
            if not rep:
                continue
            inter = len(toks & rep)
            union = len(toks | rep)
            if union and (inter / union) >= NEWS_EVENT_SIMILARITY_THRESHOLD:
                rep |= toks                  # merge: absorb tokens into the cluster
                break
        else:
            clusters.append(set(toks))       # no match -> new event cluster
    return len(clusters)


def _effective_signal_count(signals: list[dict]) -> int:
    """
    Signal count for the confidence VOLUME factor, de-duplicating news by event (Task 4):
        effective = distinct_news_events + count(non-news signals)
    Non-news types (sanctions is already one aggregate per corridor; price is one row)
    are counted as-is.
    """
    news    = [s for s in signals if s.get("signal_type") == "news"]
    non_news = [s for s in signals if s.get("signal_type") != "news"]
    return _distinct_news_event_count(news) + len(non_news)


def _compute_confidence(signals: list[dict]) -> float:
    """
    Confidence in the risk_score based on two factors:

    1. Volume factor  = min(1.0, effective_n / CONFIDENCE_FULL_SIGNAL_COUNT),
       where effective_n counts DISTINCT news events (not raw articles) + non-news
       signals — so many outlets on one incident no longer inflate confidence (Task 4).
    2. Recency factor = average recency score across signals.

    confidence = volume_factor * recency_factor
    """
    n = len(signals)
    if n == 0:
        return 0.0

    effective_n = _effective_signal_count(signals)
    volume_factor = min(1.0, effective_n / CONFIDENCE_FULL_SIGNAL_COUNT)

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

def _extract_numbers(text: str) -> list[float]:
    """Pull numeric tokens (incl. percentages) out of LLM text for the consistency
    check. A trailing '%' is normalised to a 0–1 fraction (75% -> 0.75)."""
    import re
    nums: list[float] = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(%?)", text):
        val = float(m.group(1))
        if m.group(2) == "%":
            val /= 100.0
        nums.append(val)
    return nums


def _verify_explanation_numbers(
    text: str,
    allowed_values: list[float],
    tolerance: float = 0.02,
) -> list[float]:
    """
    Cheap post-check (Task 9): return any numbers in `text` that do NOT match a
    computed/allowed value within `tolerance`. A non-empty result means the LLM
    likely introduced a figure of its own — the caller logs a warning.

    Small integers (0,1,2,…, up to the signal count) are always allowed — they are
    almost always sentence counts / list sizes, not fabricated statistics.
    """
    unverified: list[float] = []
    for n in _extract_numbers(text):
        if float(n).is_integer() and n <= max([5.0, *allowed_values]):
            continue  # plausibly a count, not a statistic
        if any(abs(n - a) <= tolerance for a in allowed_values):
            continue
        # A percentage may be written either as 75 or 0.75 — check the /100 form too.
        if any(abs(n / 100.0 - a) <= tolerance for a in allowed_values):
            continue
        unverified.append(n)
    return unverified


def get_risk_explanation(
    corridor: str,
    risk_score: float,
    contributing_signals: list[dict],
    n_signals: int,
    computed: dict | None = None,
) -> str:
    """
    Call the configured LLM (Groq by default, Gemini optional — see llm_client) to
    produce a 2-3 sentence explanation of the risk score, GROUNDED strictly in the
    structured signals + computed numbers passed in (Task 9).

    The prompt passes ONLY the structured signals and the computed figures, and
    instructs the model to reference nothing outside them and to invent no numbers.
    A cheap post-check flags any figure in the output that does not match a computed
    value (logged as a warning — the text is still returned; this is a guardrail, not
    a hard gate). If the LLM is unavailable, falls back to a deterministic template.
    Pipeline NEVER crashes on LLM failure.
    """
    computed = computed or {}
    acute_score     = computed.get("acute_score")
    sanctions_floor = computed.get("sanctions_floor")
    confidence      = computed.get("confidence")

    signal_summaries = "\n".join(
        f"- [{s.get('signal_type', 'unknown')}] severity={float(s.get('severity_hint', 0.0)):.2f} "
        f"| {s.get('text_summary', '')}"
        for s in contributing_signals
    )

    # Computed numbers block — the ONLY figures the model is allowed to cite.
    computed_lines = [f"- risk_score = {risk_score:.2f} (0–1 scale; 1.0 = certain disruption)"]
    if acute_score is not None:
        computed_lines.append(f"- acute_score (leading signals) = {acute_score:.2f}")
    if sanctions_floor is not None:
        computed_lines.append(f"- sanctions_floor (structural baseline) = {sanctions_floor:.2f}")
    if confidence is not None:
        computed_lines.append(f"- confidence = {confidence:.2f}")
    computed_block = "\n".join(computed_lines)

    prompt = (
        f"You are a supply chain risk analyst. Write a 2-3 sentence plain-English "
        f"explanation of the risk score for the {corridor} corridor.\n\n"
        f"STRICT RULES:\n"
        f"- Use ONLY the signals and computed numbers provided below.\n"
        f"- Do NOT reference any event, place, statistic, or number not present below.\n"
        f"- Do NOT invent or estimate any figures. If you cite a number, it MUST be one "
        f"of the computed numbers below, quoted exactly.\n"
        f"- Be specific about which signals drove the score.\n\n"
        f"COMPUTED NUMBERS (the only figures you may cite):\n{computed_block}\n\n"
        f"SIGNALS:\n{signal_summaries}"
    )

    try:
        text = generate_text(prompt)
        # Post-check: verify every figure in the text is a computed value.
        allowed = [v for v in (risk_score, acute_score, sanctions_floor, confidence)
                   if v is not None]
        allowed += [float(s.get("severity_hint", 0.0)) for s in contributing_signals]
        unverified = _verify_explanation_numbers(text, allowed)
        if unverified:
            logger.warning(
                "[Stage3] corridor='%s' — explanation contains number(s) not matching "
                "any computed value: %s. Possible LLM-introduced figure(s); text kept "
                "but flagged.", corridor, unverified,
            )
        logger.info(
            "[Stage3] %s explanation generated for corridor='%s'.",
            llm_status().get("provider"), corridor,
        )
        return text
    except LLMUnavailable as exc:
        logger.warning(
            "[Stage3] LLM unavailable for corridor='%s': %s. Using fallback.",
            corridor, exc,
        )
        return (
            f"Risk score {risk_score:.2f} for {corridor} based on "
            f"{n_signals} signal(s). (LLM unavailable: {exc})"
        )


def _fallback_explanation(
    corridor: str,
    risk_score: float,
    n_signals: int,
    acute_score: float | None = None,
    sanctions_floor: float | None = None,
) -> str:
    """Deterministic template explanation used when the LLM is disabled or fails.
    Reflects the acute-vs-floor model (Task 2): risk = max(acute leading signals,
    structural sanctions floor)."""
    acute = 0.0 if acute_score is None else acute_score
    floor = 0.0 if sanctions_floor is None else sanctions_floor
    driver = "structural sanctions floor" if floor >= acute else "acute leading signals"
    return (
        f"Risk score {risk_score:.2f} for {corridor} corridor based on {n_signals} "
        f"signal(s): the higher of an acute leading-signal score of {acute:.2f} "
        f"(news/shipping/price, weights renormalised over present types) and a structural "
        f"sanctions floor of {floor:.2f}. Driven by the {driver}. Confidence reflects "
        f"distinct-event volume and recency. "
        f"[LLM explanation disabled — set GROQ_API_KEY (or GEMINI_API_KEY) in .env to enable]"
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

    # --- Per-type aggregation (Task 1) -----------------------------------------
    type_severity  = _aggregate_severity_by_type(signals)
    present_types  = sorted(type_severity.keys())
    missing_types  = sorted(t for t in SIGNAL_TYPE_WEIGHTS if t not in type_severity)

    # --- Acute score (leading signals) vs sanctions floor (structural) (Task 2) -
    # The acute score is a renormalised weighted average over present LEADING types
    # (news/shipping/price). Sanctions set a persistent baseline floor. Final score
    # is max(acute, floor): acute signals raise risk above the structural baseline,
    # but risk never falls below it.
    present_leading = [t for t in present_types if t in LEADING_SIGNAL_TYPES]
    acute_score     = _acute_score(type_severity)
    sanctions_floor = _sanctions_floor(type_severity)
    risk_score      = round(max(acute_score, sanctions_floor), 4)
    leading_weights = {t: round(w, 4) for t, w in
                       _renormalized_weights(present_leading).items()}

    logger.info(
        "[Stage3] corridor='%s' — present types=%s, absent=%s | acute=%.4f "
        "(leading weights=%s) vs sanctions_floor=%.4f -> risk_score=%.4f (%s)",
        corridor, present_types, missing_types, acute_score, leading_weights,
        sanctions_floor, risk_score,
        "floor-bound" if sanctions_floor >= acute_score else "acute-driven",
    )

    confidence = _compute_confidence(signals)
    signal_ids = [s["id"] for s in signals if "id" in s]
    n          = len(signals)

    # -------------------------------------------------------------------------
    # detail (JSONB) — transparent breakdown surfaced to the API/dashboard.
    # Persisted in the risk_scores.detail column (see supabase_schema.sql).
    # Keeps the flat scalar fields (risk_score/confidence) for backward compat.
    # -------------------------------------------------------------------------
    detail = {
        "acute_score":      acute_score,       # leading-signal weighted average
        "sanctions_floor":  sanctions_floor,   # structural baseline floor
        "score_driver":     "floor" if sanctions_floor >= acute_score else "acute",
        "signals_present":  present_types,
        "signals_missing":  missing_types,
        "leading_weights":  leading_weights,   # renormalised over present leading types
        "type_severity":    {t: round(v, 4) for t, v in type_severity.items()},
        "confidence_band":  _confidence_band(risk_score, confidence),  # Task 3
    }

    if use_llm:
        explanation = get_risk_explanation(
            corridor, risk_score, signals, n,
            computed={
                "acute_score":     acute_score,
                "sanctions_floor": sanctions_floor,
                "confidence":      confidence,
            },
        )
    else:
        explanation = _fallback_explanation(
            corridor, risk_score, n, acute_score, sanctions_floor
        )

    return {
        "id":                   str(uuid.uuid4()),
        "corridor":             corridor,
        "supplier":             None,
        "risk_score":           risk_score,
        "confidence":           confidence,
        "explanation":          explanation,
        "contributing_signals": signal_ids,
        "detail":               detail,
        "source":               "real",      # live Supabase data — not mock
        "generated_at":         datetime.now(timezone.utc).isoformat(),
    }
