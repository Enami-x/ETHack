"""
/agents/reserve_optimizer.py
==============================
Stage 6 — Reserve Optimization Agent

Responsibility:
    Model SPR (Strategic Petroleum Reserve) drawdown against an active scenario's
    supply gap, producing a day-by-day drawdown schedule and a policy recommendation.

Formula philosophy — FULLY DOCUMENTED, NO BLACK BOX:
    1. Disruption window length is scenario-type-specific (see DISRUPTION_WINDOW_DAYS).
    2. Drawdown per day uses a FRONT-LOADED PIECEWISE LINEAR taper:
         - Phase 1 (first 1/3 of window): high draw — crisis response phase.
           Alternate procurement (Stage 5) not yet online; SPR bears full load.
         - Phase 2 (middle 1/3 of window): moderate draw — partial procurement online.
         - Phase 3 (final 1/3 of window): low draw — procurement largely online.
       Raw daily draws are proportional weights; they are normalized so that
       SUM(draw_pct) == 1.0 across all days (100% of the available drawdown
       is allocated across the window — no overshoot, no waste).
    3. Policy thresholds (SPR_DAYS_CRITICAL, etc.) categorize urgency and determine
       the recommended response posture.

Usage:
    from agents.reserve_optimizer import optimize_reserves
    plan = optimize_reserves(scenario)
"""

import uuid
import math
import logging
from datetime import datetime, timezone

from config import assumptions

logger = logging.getLogger(__name__)


# =============================================================================
# BASELINE CONSTANTS — now sourced from config/assumptions.py (Task 6)
# =============================================================================

# India's SPR baseline cover (days of crude-import equivalent) = strategic reserve
# actually on hand: 9.5 days at full capacity × ~64% current fill ≈ 6.08 days.
# (Was a flat 9.5.) Full sourcing + the 74-day total-buffer context live in config.
SPR_BASELINE_DAYS: float = assumptions.SPR_BASELINE_DAYS

# Estimated disruption duration by scenario type (in days).
# These are documented assumptions, not forecasts. Adjust as conditions evolve.
#
#   hormuz_partial_closure: 14 days
#     Calibration: 2025 US-Iran standoff tensions resolved in ~2 weeks at the
#     geopolitical level. Physical transit disruption typically shorter once
#     commercial shipping resumes normal routing.
#
#   opec_emergency_cut: 30 days
#     OPEC+ emergency cuts historically phase in over 30–45 days. Chosen the
#     shorter end since "emergency" cuts signal shorter political duration.
#
#   red_sea_suspension: 21 days
#     Cape of Good Hope rerouting stabilizes in 2–3 weeks per Stage 4 assumption.
#     Primary mechanism is freight cost / transit time, not volume, so disruption
#     window captures the rerouting transition period only.
DISRUPTION_WINDOW_DAYS: dict[str, int] = {
    "hormuz_partial_closure": 14,
    "opec_emergency_cut":     30,
    "red_sea_suspension":     21,
}

# Default window for unknown scenario types (defensive fallback).
DEFAULT_DISRUPTION_WINDOW_DAYS: int = 21

# Replenishment takes longer than the disruption itself.
# Assumption: contract renegotiation lag, shipping logistics, and SPR refill
# logistics add ~50% overhead on top of the disruption window.
# Source: Assumption — TESTABLE. Adjust REPLENISHMENT_OVERHEAD_FACTOR to calibrate.
REPLENISHMENT_OVERHEAD_FACTOR: float = 1.5


# =============================================================================
# POLICY THRESHOLDS — categorise urgency from SPR days remaining
# =============================================================================

# CRITICAL: below this threshold, SPR cover is dangerously low.
# Recommended posture: maximum drawdown rate + emergency procurement.
# From config: rescaled from the old 5.0 by current SPR fill (≈ 3.2) so the band
# stays meaningful against the ~6.08-day effective baseline.
SPR_DAYS_CRITICAL: float = assumptions.SPR_DAYS_CRITICAL

# CAUTION: between CAUTION and STABLE thresholds.
# Recommended posture: moderate drawdown + expedited procurement.
# From config: rescaled from the old 8.0 by current SPR fill (≈ 5.1).
SPR_DAYS_CAUTION: float = assumptions.SPR_DAYS_CAUTION

# STABLE: above this threshold.
# Recommended posture: precautionary drawdown + normal procurement diversification.
# (No threshold constant needed — implied as > SPR_DAYS_CAUTION)


# =============================================================================
# DRAWDOWN SCHEDULE — LEAD-TIME-AWARE PIECEWISE TAPER (Task 8)
# =============================================================================
#
# The old taper hardcoded procurement coming online at N/3 and 2N/3 of the window,
# implicitly ASSUMING alternate supply arrives exactly on that schedule. In reality
# procurement has a real LEAD TIME (contract execution + long-haul voyage) before the
# first replacement cargo lands — read from config.PROCUREMENT_LEAD_TIME_DAYS. Until
# that day the SPR bears the FULL supply gap; only afterwards can the draw taper.
#
# The lead time is uncertain, so we expose the tradeoff as two selectable MODES rather
# than baking one assumption in:
#
#   AGGRESSIVE — trust the lead-time estimate. Procurement is assumed online at exactly
#     lead_time days. Draw the SPR hard and front-loaded before then, taper sharply
#     after relief is expected. Conserves reserve for a tail that (if the bet holds)
#     needs little — but if procurement SLIPS, the reserve was already spent.
#
#   CONSERVATIVE — hedge that the lead time slips (× CONSERVATIVE_LEAD_SLIP_FACTOR).
#     Procurement is assumed online later, and the draw is rationed more evenly (a
#     flatter taper) so the reserve survives a longer UNAIDED gap. Costs more reserve
#     over the full window but is robust to procurement delay.
#
# Both are normalised so SUM(draw_pct) == 1.0 (100% of available drawdown allocated).
# TESTABLE constants below.

# Per-day phase weights, per mode: (high = pre-procurement crisis load, med = ramping,
# low = procurement largely online). Aggressive is steeply front-loaded; conservative
# is deliberately flatter so the reserve is rationed across a longer possible gap.
PHASE_WEIGHTS_BY_MODE: dict[str, dict[str, float]] = {
    "aggressive":   {"high": 3.0, "med": 1.5, "low": 0.5},
    "conservative": {"high": 1.5, "med": 1.1, "low": 0.8},
}

# Conservative mode assumes procurement lands this many times LATER than the nominal
# lead time (i.e. plans for slippage). Aggressive mode uses a factor of 1.0.
CONSERVATIVE_LEAD_SLIP_FACTOR: float = 1.5

# Back-compat aliases (older references expected single PHASE_WEIGHT_* names).
PHASE_WEIGHT_HIGH: float = PHASE_WEIGHTS_BY_MODE["aggressive"]["high"]
PHASE_WEIGHT_MED:  float = PHASE_WEIGHTS_BY_MODE["aggressive"]["med"]
PHASE_WEIGHT_LOW:  float = PHASE_WEIGHTS_BY_MODE["aggressive"]["low"]

VALID_DRAWDOWN_MODES = tuple(PHASE_WEIGHTS_BY_MODE.keys())


def _procurement_online_day(window_days: int, lead_time_days: int, mode: str) -> int:
    """
    Day on which alternate procurement is ASSUMED to begin substituting for the SPR.
    Aggressive trusts the nominal lead time; conservative inflates it by the slip
    factor. Clamped to [1, window_days] so the phase boundaries stay inside the window.
    """
    slip = CONSERVATIVE_LEAD_SLIP_FACTOR if mode == "conservative" else 1.0
    online = int(round(lead_time_days * slip))
    return max(1, min(window_days, online))


def _build_drawdown_schedule(
    window_days: int,
    lead_time_days: int,
    mode: str,
) -> list[dict]:
    """
    Build the normalised day-by-day drawdown schedule for `mode`, anchored to when
    procurement is assumed to come online (a function of lead time + mode).

    Returns [{"day": 1, "draw_pct": 0.xxxx}, ...] with SUM(draw_pct) == 1.0.

    Phases:
        phase1 (HIGH): days 1 .. online_day                 — SPR bears the full gap
        phase2 (MED) : days online_day+1 .. online_day+ramp — procurement ramping
        phase3 (LOW) : remaining days                       — procurement largely online
    where ramp = half of the post-online remainder (at least 1 day if any remain).
    """
    if window_days < 1:
        return []

    weights = PHASE_WEIGHTS_BY_MODE.get(mode, PHASE_WEIGHTS_BY_MODE["conservative"])
    online  = _procurement_online_day(window_days, lead_time_days, mode)
    remain  = window_days - online
    ramp    = max(1, remain // 2) if remain > 0 else 0
    p2_end  = online + ramp

    raw_weights: list[float] = []
    for day in range(1, window_days + 1):
        if day <= online:
            raw_weights.append(weights["high"])
        elif day <= p2_end:
            raw_weights.append(weights["med"])
        else:
            raw_weights.append(weights["low"])

    total = sum(raw_weights)
    return [
        {"day": day, "draw_pct": round(w / total, 6)}
        for day, w in enumerate(raw_weights, start=1)
    ]


def _build_dual_mode_schedule(
    window_days: int,
    lead_time_days: int,
    primary_mode: str,
) -> list[dict]:
    """
    Build a single drawdown_schedule array (backward-compatible: each element still has
    'day' + 'draw_pct') that ALSO carries both modes' values per day, so the lead-time
    tradeoff is visible without a schema change:
        [{"day", "draw_pct"(=primary), "draw_pct_conservative", "draw_pct_aggressive"}]
    The dashboard chart reads 'draw_pct' (the primary mode) and ignores the extras.
    """
    cons = {d["day"]: d["draw_pct"]
            for d in _build_drawdown_schedule(window_days, lead_time_days, "conservative")}
    aggr = {d["day"]: d["draw_pct"]
            for d in _build_drawdown_schedule(window_days, lead_time_days, "aggressive")}
    primary = cons if primary_mode == "conservative" else aggr

    return [
        {
            "day": day,
            "draw_pct": primary[day],
            "draw_pct_conservative": cons[day],
            "draw_pct_aggressive": aggr[day],
        }
        for day in range(1, window_days + 1)
    ]


# =============================================================================
# POLICY RECOMMENDATION — template-based, fully deterministic
# =============================================================================

def _policy_label(days_remaining: float) -> str:
    """Return the status label for SPR days of cover remaining."""
    if days_remaining < SPR_DAYS_CRITICAL:
        return "CRITICAL"
    elif days_remaining < SPR_DAYS_CAUTION:
        return "CAUTION"
    else:
        return "STABLE"


def _build_policy_recommendation(
    scenario_type: str,
    severity: float,
    supply_gap_pct: float,
    days_remaining: float,
    window_days: int,
    replenishment_days: float,
    lead_time_days: int,
    mode: str,
) -> str:
    """
    Generate a template-based, one-paragraph policy recommendation.
    References all key numbers and named thresholds — explicit and auditable.
    """
    label = _policy_label(days_remaining)
    gap_pct_display = round(supply_gap_pct * 100, 1)

    if label == "CRITICAL":
        urgency_text = (
            f"SPR cover of {days_remaining:.2f} days is CRITICAL (below the "
            f"{SPR_DAYS_CRITICAL}-day threshold). Immediate maximum-rate SPR release "
            f"is required. Stage 5 procurement execution must be treated as an "
            f"emergency — prioritise existing relationships (Russia, Nigeria) for "
            f"fastest contract activation. Simultaneously engage IEA emergency "
            f"stock release coordination."
        )
    elif label == "CAUTION":
        urgency_text = (
            f"SPR cover of {days_remaining:.2f} days is in the CAUTION zone "
            f"({SPR_DAYS_CRITICAL}–{SPR_DAYS_CAUTION} days). Expedited but not "
            f"maximum-rate SPR release is appropriate. Accelerate Stage 5 procurement "
            f"execution, focusing on non-Hormuz suppliers. Monitor corridor status "
            f"for escalation triggers."
        )
    else:  # STABLE
        urgency_text = (
            f"SPR cover of {days_remaining:.2f} days is STABLE (above the "
            f"{SPR_DAYS_CAUTION}-day threshold). A precautionary front-loaded "
            f"drawdown is recommended to signal policy readiness and provide a "
            f"buffer while Stage 5 procurement diversification is executed. "
            f"No emergency measures required at current severity."
        )

    stype_display = scenario_type.replace("_", " ").title()

    # Lead-time-aware taper description (Task 8): the taper is anchored to when
    # procurement is assumed online (a function of lead time + mode), not a fixed N/3.
    cons_online = _procurement_online_day(window_days, lead_time_days, "conservative")
    aggr_online = _procurement_online_day(window_days, lead_time_days, "aggressive")
    mode_text = (
        f"Drawdown mode = {mode.upper()} over a {window_days}-day window with an assumed "
        f"procurement lead time of {lead_time_days} days. "
        f"AGGRESSIVE trusts that lead time (procurement online ~day {aggr_online}; SPR drawn "
        f"hard and front-loaded before then, tapering sharply after) — conserves reserve but "
        f"is exposed if procurement slips. CONSERVATIVE plans for slippage "
        f"(×{CONSERVATIVE_LEAD_SLIP_FACTOR}; procurement assumed online ~day {cons_online}; "
        f"SPR rationed more evenly) — robust to delay but spends more reserve across the "
        f"window. Both per-day curves are in drawdown_schedule (draw_pct = the "
        f"{mode.upper()} curve; draw_pct_conservative / draw_pct_aggressive alongside)."
    )

    return (
        f"[{label}] {stype_display} scenario at severity {severity:.1f} creates a "
        f"{gap_pct_display}% supply gap. {urgency_text} {mode_text} "
        f"Replenishment window estimated at {replenishment_days:.0f} days post-disruption "
        f"(disruption window × {REPLENISHMENT_OVERHEAD_FACTOR}× overhead for contract "
        f"renegotiation lag). "
        f"Threshold reference: CRITICAL <{SPR_DAYS_CRITICAL}d | "
        f"CAUTION {SPR_DAYS_CRITICAL}–{SPR_DAYS_CAUTION}d | STABLE >{SPR_DAYS_CAUTION}d."
    )


# =============================================================================
# PUBLIC API
# =============================================================================

def optimize_reserves(scenario: dict, mode: str = "conservative") -> dict:
    """
    Compute a reserve_plans row (§5 Stage 6 schema) for a given Stage 4 scenario.

    Args:
        scenario: A Stage 4 run_scenario() output or Supabase scenarios row.
                  Required keys: scenario_type, severity, supply_gap_pct,
                  spr_days_remaining_estimate. 'id' used as scenario_id if present.
        mode:     Drawdown posture — "conservative" (default; hedge against procurement
                  lead-time slippage, ration the SPR more evenly) or "aggressive" (trust
                  the lead-time estimate, front-load the draw). Governs which per-day
                  curve is the primary draw_pct; BOTH curves are always returned so the
                  lead-time tradeoff is visible (Task 8).

    Returns:
        Dict matching the reserve_plans schema. drawdown_schedule stays a list of
        {"day", "draw_pct"} (chart-compatible) but each element ALSO carries
        draw_pct_conservative / draw_pct_aggressive:
        {
            "id":                               str (uuid4),
            "scenario_id":                      str | None,
            "drawdown_schedule":                list[dict],
            "days_of_cover_remaining":          float,       # passed through from Stage 4
            "replenishment_window_estimate_days": float,
            "policy_recommendation":            str,
            "generated_at":                     str (ISO8601),
        }

    Raises:
        ValueError: if scenario is missing required keys or mode is invalid.
    """
    required = {"scenario_type", "severity", "supply_gap_pct", "spr_days_remaining_estimate"}
    missing  = required - set(scenario.keys())
    if missing:
        raise ValueError(f"optimize_reserves() — scenario missing keys: {missing}")
    if mode not in VALID_DRAWDOWN_MODES:
        raise ValueError(
            f"optimize_reserves() — invalid mode '{mode}'. "
            f"Valid: {list(VALID_DRAWDOWN_MODES)}"
        )

    scenario_type   = scenario["scenario_type"]
    severity        = float(scenario["severity"])
    supply_gap_pct  = float(scenario["supply_gap_pct"])
    days_remaining  = float(scenario["spr_days_remaining_estimate"])
    scenario_id     = scenario.get("id")

    # Resolve disruption window
    window_days = DISRUPTION_WINDOW_DAYS.get(scenario_type, DEFAULT_DISRUPTION_WINDOW_DAYS)
    if scenario_type not in DISRUPTION_WINDOW_DAYS:
        logger.warning(
            "[Stage6] Unknown scenario_type '%s' — using default window %d days.",
            scenario_type, DEFAULT_DISRUPTION_WINDOW_DAYS,
        )

    # Procurement lead time (from config) drives when the SPR taper can begin (Task 8).
    lead_time_days = assumptions.PROCUREMENT_LEAD_TIME_DAYS

    replenishment_days = round(window_days * REPLENISHMENT_OVERHEAD_FACTOR, 1)

    drawdown_schedule = _build_dual_mode_schedule(window_days, lead_time_days, mode)

    policy_recommendation = _build_policy_recommendation(
        scenario_type   = scenario_type,
        severity        = severity,
        supply_gap_pct  = supply_gap_pct,
        days_remaining  = days_remaining,
        window_days     = window_days,
        replenishment_days = replenishment_days,
        lead_time_days  = lead_time_days,
        mode            = mode,
    )

    return {
        "id":                                 str(uuid.uuid4()),
        "scenario_id":                        scenario_id,
        "drawdown_schedule":                  drawdown_schedule,
        "days_of_cover_remaining":            round(days_remaining, 4),
        "replenishment_window_estimate_days": replenishment_days,
        "policy_recommendation":              policy_recommendation,
        "generated_at":                       datetime.now(timezone.utc).isoformat(),
    }
