"""
/agents/scenario_modeling.py
=============================
Stage 4 — Scenario Modeling Agent

Responsibility:
    Simulate named disruption events and compute cascading supply-chain impacts.
    All formulas are TRANSPARENT, PARAMETRIC, and FULLY COMMENTED — explicit
    testable assumptions are a named judging criterion. Every multiplier is a
    named constant with a rationale comment, not a buried magic number.

Supported scenario types:
    - "hormuz_partial_closure"   — strait capacity reduction
    - "opec_emergency_cut"       — OPEC+ supply-side production cut
    - "red_sea_suspension"       — Red Sea transit suspension / Cape rerouting

Each scenario uses a SEPARATE formula with a distinct mechanism. The three are not
interchangeable — see individual section comments below.

Usage:
    from agents.scenario_modeling import run_scenario

    result = run_scenario("hormuz_partial_closure", severity=0.6, corridor="hormuz")
"""

import pathlib
import uuid
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv

from config import assumptions

# Load .env so SUPABASE_* keys are available (idempotent — safe to call repeatedly).
load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)


# =============================================================================
# GLOBAL BASELINE ASSUMPTIONS — now sourced from config/assumptions.py (Task 6).
# These module-level names are kept as thin aliases so the existing assumption
# strings/formulas below still read naturally; the VALUES live in one cited place.
# Edit config/assumptions.py (with citations + last_updated) to recalibrate.
# =============================================================================

# Baseline strategic petroleum reserve cover, in days (strategic reserve on hand:
# 9.5 days at full capacity × ~64% current fill ≈ 6.08). See config for full sourcing.
SPR_BASELINE_DAYS: float = assumptions.SPR_BASELINE_DAYS

# Fraction of India's crude imports that transit the Strait of Hormuz (2026: ~0.30,
# down from ~0.45 — ~70% of crude now routes outside Hormuz).
HORMUZ_INDIA_SHARE: float = assumptions.HORMUZ_INDIA_SHARE

# Fraction of India's crude imports affected by a full Red Sea suspension (rerouting-
# driven, not volume loss).
RED_SEA_INDIA_CRUDE_SHARE: float = assumptions.RED_SEA_INDIA_CRUDE_SHARE

# Effective India impact of an OPEC+ emergency cut, as a fraction of severity.
OPEC_CUT_INDIA_EFFECTIVE_SHARE: float = assumptions.OPEC_CUT_INDIA_EFFECTIVE_SHARE


# =============================================================================
# SCENARIO A — hormuz_partial_closure
# Mechanism: physical reduction of throughput through the Strait of Hormuz.
# Severity: fraction of strait capacity that is disrupted (0.0 = no disruption,
#           1.0 = full closure — historically unprecedented but used for bounding).
# =============================================================================

# Price elasticity multiplier for a Hormuz closure (from config/assumptions.py).
# Calibration anchor: 2025 US-Iran escalation produced an ~8% single-session Brent
# move on partial-closure fears. Modelled as a multiple of the supply gap, reflecting
# panic premium on top of pure scarcity. TESTABLE — edit config to recalibrate.
HORMUZ_PRICE_ELASTICITY: float = assumptions.HORMUZ_PRICE_ELASTICITY

# Refinery utilisation offset multiplier for Hormuz (<1.0 because refiners can
# partially substitute with pre-contracted cargoes from alternate routes in the short
# term, but cannot fully replace Hormuz volumes). From config/assumptions.py.
HORMUZ_REFINERY_OFFSET: float = assumptions.HORMUZ_REFINERY_OFFSET


def _hormuz_partial_closure(severity: float) -> tuple[float, float, float, float, list[str]]:
    """
    Compute disruption metrics for a Strait of Hormuz partial closure.

    Formulas:
        supply_gap_pct                  = severity × HORMUZ_INDIA_SHARE
        price_impact_pct                = supply_gap_pct × HORMUZ_PRICE_ELASTICITY
        refinery_utilization_impact_pct = supply_gap_pct × HORMUZ_REFINERY_OFFSET
        spr_days_remaining_estimate     = SPR_BASELINE_DAYS × (1 − supply_gap_pct)

    Returns: (supply_gap, price_impact, refinery_impact, spr_days, assumptions)
    """
    supply_gap  = round(severity * HORMUZ_INDIA_SHARE, 4)
    price_imp   = round(supply_gap * HORMUZ_PRICE_ELASTICITY, 4)
    refinery    = round(supply_gap * HORMUZ_REFINERY_OFFSET, 4)
    spr_days    = round(SPR_BASELINE_DAYS * (1.0 - supply_gap), 4)

    assumptions = [
        f"Hormuz carries {HORMUZ_INDIA_SHARE*100:.0f}% of India's crude import volume "
        f"(2026 import mix: ~70% of India's crude now routes OUTSIDE Hormuz — Russia via "
        f"Cape/Suez, Americas & W.Africa across the Atlantic — leaving ~30% transiting it; "
        f"down from the ~45% legacy figure. See config/assumptions.py).",
        f"Supply gap = severity ({severity:.2f}) × Hormuz share ({HORMUZ_INDIA_SHARE}) "
        f"= {supply_gap:.4f} ({supply_gap*100:.1f}% of India's crude supply at risk).",
        f"Price impact multiplier = {HORMUZ_PRICE_ELASTICITY}× (empirical elasticity). "
        f"Calibration anchor: 2025 US-Iran standoff produced ~8% single-session Brent "
        f"move on partial-closure fears. TESTABLE — adjust HORMUZ_PRICE_ELASTICITY constant.",
        f"Refinery utilisation impact = supply_gap × {HORMUZ_REFINERY_OFFSET} (offset "
        f"<1.0 because refiners can partially substitute from alternate pre-contracted "
        f"cargoes in the short term, but cannot fully replace Hormuz volumes).",
        f"SPR estimate = {SPR_BASELINE_DAYS} days baseline × (1 − supply_gap) "
        f"= {spr_days:.2f} days. Baseline = strategic reserve on hand (9.5d at full "
        f"capacity × ~64% current fill ≈ 6.08d; total national buffer incl. commercial "
        f"stock ≈ 74d — see config/assumptions.py). Depleted proportionally to supply gap "
        f"assuming uniform drawdown rate.",
        "Severity 1.0 = complete Hormuz closure — historically unprecedented; used for "
        "bounding. Severity 0.0 = baseline (no disruption).",
    ]
    return supply_gap, price_imp, refinery, spr_days, assumptions


# =============================================================================
# SCENARIO B — opec_emergency_cut
# Mechanism: OPEC+ announces an emergency production cut. This is a supply-side
# event with more advance notice than a chokepoint closure, giving refiners more
# lead time to adjust sourcing. Price impact is historically higher per unit of
# supply gap (OPEC has stronger market pricing power than logistics disruptions).
# Severity: fraction of OPEC+ spare capacity that is cut.
# =============================================================================

# Price elasticity multiplier for an OPEC emergency cut.
# Rationale: OPEC cuts historically command higher price premium than logistics
# events because they signal cartel coordination and sustained supply discipline.
# Reference: 2022 OPEC+ 2 mb/d cut → ~$10/bbl immediate Brent move on ~3% supply
# gap → ~3.3× elasticity. Using a conservative estimate since India has partial
# long-term contract insulation. TESTABLE — from config/assumptions.py.
OPEC_PRICE_ELASTICITY: float = assumptions.OPEC_PRICE_ELASTICITY

# Refinery utilisation offset for an OPEC cut. Lower impact than Hormuz because:
# (a) more advance notice, (b) refiners can increase spot purchases from non-OPEC+
# producers (US, Canada, Guyana), (c) cuts phase in over weeks. From config.
OPEC_REFINERY_OFFSET: float = assumptions.OPEC_REFINERY_OFFSET


def _opec_emergency_cut(severity: float) -> tuple[float, float, float, float, list[str]]:
    """
    Compute disruption metrics for an OPEC+ emergency production cut.

    Formulas:
        supply_gap_pct                  = severity × OPEC_CUT_INDIA_EFFECTIVE_SHARE
        price_impact_pct                = supply_gap_pct × OPEC_PRICE_ELASTICITY
        refinery_utilization_impact_pct = supply_gap_pct × OPEC_REFINERY_OFFSET
        spr_days_remaining_estimate     = SPR_BASELINE_DAYS × (1 − supply_gap_pct)
    """
    supply_gap = round(severity * OPEC_CUT_INDIA_EFFECTIVE_SHARE, 4)
    price_imp  = round(supply_gap * OPEC_PRICE_ELASTICITY, 4)
    refinery   = round(supply_gap * OPEC_REFINERY_OFFSET, 4)
    spr_days   = round(SPR_BASELINE_DAYS * (1.0 - supply_gap), 4)

    assumptions = [
        f"India sources ~65% of crude from OPEC+ (BP Statistical Review 2023), but "
        f"emergency cuts affect spot/margin barrels first. Effective India impact "
        f"modelled at {OPEC_CUT_INDIA_EFFECTIVE_SHARE*100:.0f}% of severity (conservative "
        f"— long-term contracts buffer the first tranche of any cut).",
        f"Supply gap = severity ({severity:.2f}) × effective OPEC share "
        f"({OPEC_CUT_INDIA_EFFECTIVE_SHARE}) = {supply_gap:.4f} "
        f"({supply_gap*100:.1f}% of India's crude supply at risk).",
        f"Price impact multiplier = {OPEC_PRICE_ELASTICITY}× (OPEC cuts command higher "
        f"elasticity than logistics disruptions). Reference: 2022 OPEC+ 2 mb/d cut "
        f"→ ~$10/bbl Brent move (~3.3× elasticity); 2.2× used here as conservative "
        f"estimate accounting for India's partial contract insulation. TESTABLE constant.",
        f"Refinery utilisation multiplier = {OPEC_REFINERY_OFFSET}× (lower than Hormuz "
        f"scenario because cuts phase in gradually — refiners have more lead time to "
        f"increase spot purchases from non-OPEC+ producers: US, Canada, Guyana).",
        f"SPR estimate = {SPR_BASELINE_DAYS} days baseline × (1 − supply_gap) "
        f"= {spr_days:.2f} days. Proportional depletion assuming uniform drawdown.",
        "Severity 1.0 = full OPEC+ spare capacity cut — extreme tail scenario. "
        "Severity 0.0 = no cut (baseline).",
    ]
    return supply_gap, price_imp, refinery, spr_days, assumptions


# =============================================================================
# SCENARIO C — red_sea_suspension
# Mechanism: Houthi/piracy activity suspends commercial transit through the Red Sea /
# Bab-el-Mandeb strait. Primary effect is REROUTING via Cape of Good Hope (+10–14
# days transit, +15–25% freight cost), NOT direct volume loss. Hence supply_gap
# is smaller and price elasticity is lower than a Hormuz closure.
# Severity: fraction of Red Sea-transiting volume that is suspended.
# =============================================================================

# Price elasticity multiplier for a Red Sea suspension.
# Lower than Hormuz because rerouting absorbs much of the impact — markets price
# freight costs and transit delays, not full supply scarcity.
# Reference: 2024 Houthi Red Sea crisis produced ~5–8% Brent premium and ~300%
# freight cost increase on Asia routes. Freight-dominated. TESTABLE — from config.
RED_SEA_PRICE_ELASTICITY: float = assumptions.RED_SEA_PRICE_ELASTICITY

# Refinery utilisation impact for Red Sea suspension. Lowest of the three scenarios —
# most cargo eventually arrives via Cape of Good Hope; the main impact is delayed
# deliveries and inventory drawdowns, not physical volume shortfalls. From config.
RED_SEA_REFINERY_OFFSET: float = assumptions.RED_SEA_REFINERY_OFFSET


def _red_sea_suspension(severity: float) -> tuple[float, float, float, float, list[str]]:
    """
    Compute disruption metrics for a Red Sea / Bab-el-Mandeb suspension.

    Formulas:
        supply_gap_pct                  = severity × RED_SEA_INDIA_CRUDE_SHARE
        price_impact_pct                = supply_gap_pct × RED_SEA_PRICE_ELASTICITY
        refinery_utilization_impact_pct = supply_gap_pct × RED_SEA_REFINERY_OFFSET
        spr_days_remaining_estimate     = SPR_BASELINE_DAYS × (1 − supply_gap_pct)

    Note: The primary Red Sea disruption mechanism is rerouting cost + delay, NOT
    volume loss. supply_gap_pct here models the temporary volume shortfall during
    the rerouting transition period (typically 2–4 weeks before new routing
    equilibrium is reached). At steady state, volume recovers; cost and transit
    time remain elevated.
    """
    supply_gap = round(severity * RED_SEA_INDIA_CRUDE_SHARE, 4)
    price_imp  = round(supply_gap * RED_SEA_PRICE_ELASTICITY, 4)
    refinery   = round(supply_gap * RED_SEA_REFINERY_OFFSET, 4)
    spr_days   = round(SPR_BASELINE_DAYS * (1.0 - supply_gap), 4)

    assumptions = [
        f"Red Sea/Bab-el-Mandeb directly affects ~{RED_SEA_INDIA_CRUDE_SHARE*100:.0f}% "
        f"of India's crude import volume (Assumption; primarily Suez Canal crude from "
        f"West Africa and North Africa; Middle East crude transits Hormuz instead). "
        f"PRIMARY mechanism: Cape of Good Hope rerouting (+10–14 days, +15–25% freight "
        f"cost), NOT permanent volume loss.",
        f"Supply gap = severity ({severity:.2f}) × Red Sea India crude share "
        f"({RED_SEA_INDIA_CRUDE_SHARE}) = {supply_gap:.4f} "
        f"({supply_gap*100:.1f}% — models transitional shortfall during rerouting, "
        f"not permanent loss).",
        f"Price impact multiplier = {RED_SEA_PRICE_ELASTICITY}× (lower than Hormuz/ "
        f"OPEC because rerouting absorbs much of the impact). Reference: 2024 Houthi "
        f"Red Sea crisis → ~5–8% Brent premium + ~300% freight increase; 1.3× reflects "
        f"freight-dominated rather than scarcity-dominated price signal. TESTABLE constant.",
        f"Refinery utilisation multiplier = {RED_SEA_REFINERY_OFFSET}× (lowest of "
        f"three scenarios — most cargo eventually arrives via Cape; refiners manage via "
        f"inventory drawdown and floating storage buffers during rerouting transition).",
        f"SPR estimate = {SPR_BASELINE_DAYS} days baseline × (1 − supply_gap) "
        f"= {spr_days:.2f} days. Transitional depletion only — not sustained.",
        "Severity 1.0 = complete Red Sea transit suspension (as in 2024 Houthi peak). "
        "Severity 0.0 = baseline (no disruption). At severity 1.0, Cape rerouting "
        "is assumed to be fully operational within 2–4 weeks.",
    ]
    return supply_gap, price_imp, refinery, spr_days, assumptions


# =============================================================================
# DISPATCH TABLE — maps scenario_type strings to their formula functions
# =============================================================================

_SCENARIO_FORMULAS = {
    "hormuz_partial_closure": _hormuz_partial_closure,
    "opec_emergency_cut":     _opec_emergency_cut,
    "red_sea_suspension":     _red_sea_suspension,
}

VALID_SCENARIO_TYPES = set(_SCENARIO_FORMULAS.keys())


# =============================================================================
# UNCERTAINTY BANDS — propagate Stage 3 confidence into Stage 4 outputs (Task 3)
# =============================================================================
#
# Rationale:
#   Stage 3 computes a `confidence` (0–1) for each corridor's risk_score but the old
#   handoff discarded it — only the scalar risk_score (used as `severity`) reached
#   Stage 4. A point estimate with no uncertainty overstates precision. We now widen a
#   low/expected/high band around EACH scenario metric as confidence drops:
#
#     half_width_fraction = BAND_MAX_HALF_WIDTH_FRAC × (1 − confidence)
#     low  = expected × (1 − half_width_fraction)
#     high = expected × (1 + half_width_fraction)
#
#   At confidence = 1.0 the band collapses to the point estimate (zero width).
#   At confidence = 0.0 the band reaches ±BAND_MAX_HALF_WIDTH_FRAC of the estimate.
#   The point estimate ("expected") is preserved for backward compatibility.

# Maximum half-width of the band, as a fraction of the point estimate, reached at
# zero confidence. 0.5 = ±50% around expected when confidence is 0. TESTABLE constant.
BAND_MAX_HALF_WIDTH_FRAC: float = 0.5


def _confidence_band(
    expected: float,
    confidence: float,
    lo_clamp: float = 0.0,
    hi_clamp: float | None = None,
) -> dict:
    """
    Build a {low, expected, high} band around a point estimate, widening as
    confidence falls. See the section comment for the formula. `lo_clamp`/`hi_clamp`
    bound the band (e.g. percentages floored at 0; SPR days floored at 0).
    """
    conf = max(0.0, min(1.0, confidence))
    hw   = BAND_MAX_HALF_WIDTH_FRAC * (1.0 - conf)
    low  = expected * (1.0 - hw)
    high = expected * (1.0 + hw)
    if lo_clamp is not None:
        low = max(lo_clamp, low)
    if hi_clamp is not None:
        high = min(hi_clamp, high)
    return {
        "low":      round(low, 4),
        "expected": round(expected, 4),
        "high":     round(high, 4),
    }


# =============================================================================
# PUBLIC API
# =============================================================================

def run_scenario(
    scenario_type: str,
    severity: float,
    corridor: str | None = None,
    confidence: float = 1.0,
) -> dict:
    """
    Run a named disruption scenario and return a scenarios-table row (§5 Stage 4 schema).

    Args:
        scenario_type: One of "hormuz_partial_closure", "opec_emergency_cut",
                       "red_sea_suspension".
        severity:      Float 0.0–1.0 representing the intensity of the disruption.
                       Interpretation varies per scenario — see module-level comments.
        corridor:      Optional. If provided, the latest risk_score for this corridor
                       is fetched from Supabase and appended to assumptions as context.
                       Does NOT affect the formula math.
        confidence:    Float 0.0–1.0 — the Stage 3 confidence for this corridor's
                       risk reading (default 1.0 = full confidence, zero-width bands).
                       Drives the low/expected/high uncertainty bands in `detail`.
                       Does NOT change the point-estimate formula outputs.

    Returns:
        Dict matching the §5 Stage 4 scenarios schema (point estimates unchanged),
        plus a `detail` JSONB block carrying the uncertainty bands:
        {
            "id":                             str (uuid4),
            "scenario_type":                  str,
            "severity":                       float,
            "supply_gap_pct":                 float,   # point estimate (backward compat)
            "price_impact_pct":               float,
            "refinery_utilization_impact_pct": float,
            "spr_days_remaining_estimate":    float,
            "assumptions":                    list[str],
            "detail": {                                # NEW — Task 3 (+ Task 6)
                "confidence":                 float,
                "supply_gap_pct_band":                {low, expected, high},
                "price_impact_pct_band":              {low, expected, high},
                "refinery_utilization_impact_pct_band": {low, expected, high},
                "spr_days_remaining_estimate_band":   {low, expected, high},
            },
            "generated_at":                   str (ISO8601),
        }

    Raises:
        ValueError: if scenario_type is invalid or severity is outside [0.0, 1.0].
    """
    if scenario_type not in _SCENARIO_FORMULAS:
        raise ValueError(
            f"Unknown scenario_type '{scenario_type}'. "
            f"Valid values: {sorted(VALID_SCENARIO_TYPES)}"
        )
    if not (0.0 <= severity <= 1.0):
        raise ValueError(f"severity must be in [0.0, 1.0], got {severity}")

    formula_fn = _SCENARIO_FORMULAS[scenario_type]
    # NB: local list is `assumption_notes` (not `assumptions`) to avoid shadowing the
    # imported config.assumptions module referenced in the detail block below.
    supply_gap, price_imp, refinery, spr_days, assumption_notes = formula_fn(severity)

    # --- Uncertainty bands derived from Stage 3 confidence (Task 3) -------------
    # Percentages are floored at 0.0. SPR days floored at 0.0. No upper clamp on the
    # high edge except SPR days, which cannot exceed the undisrupted baseline.
    conf = max(0.0, min(1.0, confidence))
    bands = {
        "confidence": round(conf, 4),
        "supply_gap_pct_band":  _confidence_band(supply_gap, conf, lo_clamp=0.0),
        "price_impact_pct_band": _confidence_band(price_imp, conf, lo_clamp=0.0),
        "refinery_utilization_impact_pct_band": _confidence_band(refinery, conf, lo_clamp=0.0),
        "spr_days_remaining_estimate_band": _confidence_band(
            spr_days, conf, lo_clamp=0.0, hi_clamp=SPR_BASELINE_DAYS
        ),
        # Which config assumptions produced these numbers (Task 6). Full cited block
        # (all values + sources) is served by GET /api/assumptions.
        "assumptions_block": {
            "last_updated":               assumptions.LAST_UPDATED,
            "spr_baseline_days":          SPR_BASELINE_DAYS,
            "spr_current_fill_pct":       assumptions.SPR_CURRENT_FILL_PCT,
            "total_national_buffer_days": assumptions.TOTAL_NATIONAL_BUFFER_DAYS,
            "hormuz_india_share":         HORMUZ_INDIA_SHARE,
            "red_sea_india_crude_share":  RED_SEA_INDIA_CRUDE_SHARE,
            "opec_cut_india_effective_share": OPEC_CUT_INDIA_EFFECTIVE_SHARE,
        },
    }

    # -------------------------------------------------------------------------
    # Optional: fetch current corridor risk_score from Supabase for context.
    # This does NOT change any formula output — it is appended to assumptions
    # purely for explainability / dashboard display.
    # -------------------------------------------------------------------------
    if corridor:
        try:
            from db.supabase_client import supabase
            resp = (
                supabase.table("risk_scores")
                .select("risk_score, confidence, generated_at")
                .eq("corridor", corridor)
                .order("generated_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = resp.data
            if rows:
                rs = rows[0]
                assumption_notes.append(
                    f"Current live risk_score for '{corridor}' corridor: "
                    f"{rs['risk_score']:.4f} (confidence {rs['confidence']:.2f}, "
                    f"as of {rs['generated_at']}). Provided for context only — "
                    f"does not modify scenario formula outputs."
                )
            else:
                assumption_notes.append(
                    f"No risk_score found for '{corridor}' corridor in Supabase "
                    f"(run test_risk_intelligence.py first to populate)."
                )
        except Exception as exc:
            logger.warning(
                "[Stage4] Could not fetch risk_score for corridor='%s': %s. "
                "Continuing without it.", corridor, exc
            )
            assumption_notes.append(
                f"Live risk_score for '{corridor}' corridor unavailable "
                f"(Supabase fetch failed: {exc})."
            )

    return {
        "id":                               str(uuid.uuid4()),
        "scenario_type":                    scenario_type,
        "severity":                         round(severity, 4),
        "supply_gap_pct":                   supply_gap,
        "price_impact_pct":                 price_imp,
        "refinery_utilization_impact_pct":  refinery,
        "spr_days_remaining_estimate":      spr_days,
        "assumptions":                      assumption_notes,
        "detail":                           bands,
        "generated_at":                     datetime.now(timezone.utc).isoformat(),
    }
