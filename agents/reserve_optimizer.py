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

logger = logging.getLogger(__name__)


# =============================================================================
# BASELINE CONSTANTS — sourced from the problem statement
# =============================================================================

# India's SPR baseline cover (days of crude import equivalent).
# Source: problem statement — "India's SPR provides ~9.5 days of cover".
SPR_BASELINE_DAYS: float = 9.5

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
SPR_DAYS_CRITICAL: float = 5.0

# CAUTION: between CAUTION and STABLE thresholds.
# Recommended posture: moderate drawdown + expedited procurement.
SPR_DAYS_CAUTION: float = 8.0

# STABLE: above this threshold.
# Recommended posture: precautionary drawdown + normal procurement diversification.
# (No threshold constant needed — implied as > SPR_DAYS_CAUTION)


# =============================================================================
# DRAWDOWN SCHEDULE — FRONT-LOADED PIECEWISE LINEAR TAPER
# =============================================================================
#
# Mechanism:
#   Divide the disruption window into 3 equal phases.
#   Assign a PHASE_WEIGHT to each phase — these are relative weights per DAY
#   within the phase, not absolute fractions:
#
#     Phase 1 weight per day: PHASE_WEIGHT_HIGH   (crisis onset — full SPR load)
#     Phase 2 weight per day: PHASE_WEIGHT_MED    (partial procurement online)
#     Phase 3 weight per day: PHASE_WEIGHT_LOW    (procurement largely substituting)
#
#   Raw weight for day d:
#       if d in Phase 1: raw_weight[d] = PHASE_WEIGHT_HIGH
#       if d in Phase 2: raw_weight[d] = PHASE_WEIGHT_MED
#       if d in Phase 3: raw_weight[d] = PHASE_WEIGHT_LOW
#
#   Normalised draw_pct[d] = raw_weight[d] / SUM(raw_weight)
#   This guarantees SUM(draw_pct) == 1.0 exactly (all available drawdown allocated).
#
# Rationale for front-loading:
#   Day 1–N/3: Stage 5 procurement (alternate sourcing) is not yet operational.
#     Ships take days to redirect; new contracts take time to execute.
#     SPR must compensate at full rate.
#   Day N/3–2N/3: Some alternate procurement online (e.g. Russia / Nigeria cargoes
#     already en route). SPR supplements rather than replaces.
#   Day 2N/3–N: Procurement largely online; SPR tapers to near-zero as new
#     cargoes arrive and inventory normalises.
#
# TESTABLE constants — adjust phase weights to change the taper shape:

PHASE_WEIGHT_HIGH: float = 3.0  # front-loaded phase (days 1 to N//3)
PHASE_WEIGHT_MED:  float = 1.5  # middle phase       (days N//3+1 to 2*N//3)
PHASE_WEIGHT_LOW:  float = 0.5  # tail phase          (days 2*N//3+1 to N)


def _build_drawdown_schedule(window_days: int) -> list[dict]:
    """
    Build the normalised day-by-day drawdown schedule.

    Returns a list of dicts: [{"day": 1, "draw_pct": 0.xxxx}, ...]
    where SUM(draw_pct) == 1.0 (100% of available drawdown allocated).

    Phase boundaries use integer division to handle non-divisible windows gracefully:
        phase1: days 1 .. p1_end      (first ~1/3)
        phase2: days p1_end+1 .. p2_end (middle ~1/3)
        phase3: days p2_end+1 .. window (final ~1/3)
    """
    if window_days < 1:
        return []

    p1_end = window_days // 3          # end of phase 1 (1-indexed day count)
    p2_end = (2 * window_days) // 3    # end of phase 2

    # Assign raw weights
    raw_weights: list[float] = []
    for day in range(1, window_days + 1):
        if day <= p1_end:
            raw_weights.append(PHASE_WEIGHT_HIGH)
        elif day <= p2_end:
            raw_weights.append(PHASE_WEIGHT_MED)
        else:
            raw_weights.append(PHASE_WEIGHT_LOW)

    total = sum(raw_weights)

    schedule: list[dict] = []
    for day, w in enumerate(raw_weights, start=1):
        draw = round(w / total, 6)
        schedule.append({"day": day, "draw_pct": draw})

    return schedule


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
    return (
        f"[{label}] {stype_display} scenario at severity {severity:.1f} creates a "
        f"{gap_pct_display}% supply gap. {urgency_text} "
        f"Front-loaded SPR drawdown is scheduled over {window_days} days "
        f"(heavier draws in days 1–{window_days//3}, tapering as alternate procurement "
        f"comes online by days {(2*window_days)//3}–{window_days}). "
        f"Replenishment window estimated at {replenishment_days:.0f} days post-disruption "
        f"(disruption window × {REPLENISHMENT_OVERHEAD_FACTOR}× overhead for contract "
        f"renegotiation lag). "
        f"Threshold reference: CRITICAL <{SPR_DAYS_CRITICAL}d | "
        f"CAUTION {SPR_DAYS_CRITICAL}–{SPR_DAYS_CAUTION}d | STABLE >{SPR_DAYS_CAUTION}d."
    )


# =============================================================================
# PUBLIC API
# =============================================================================

def optimize_reserves(scenario: dict) -> dict:
    """
    Compute a reserve_plans row (§5 Stage 6 schema) for a given Stage 4 scenario.

    Args:
        scenario: A Stage 4 run_scenario() output or Supabase scenarios row.
                  Required keys: scenario_type, severity, supply_gap_pct,
                  spr_days_remaining_estimate. 'id' used as scenario_id if present.

    Returns:
        Dict matching the reserve_plans schema exactly:
        {
            "id":                               str (uuid4),
            "scenario_id":                      str | None,
            "drawdown_schedule":                list[dict],  # [{"day": int, "draw_pct": float}]
            "days_of_cover_remaining":          float,       # passed through from Stage 4
            "replenishment_window_estimate_days": float,
            "policy_recommendation":            str,
            "generated_at":                     str (ISO8601),
        }

    Raises:
        ValueError: if scenario is missing required keys.
    """
    required = {"scenario_type", "severity", "supply_gap_pct", "spr_days_remaining_estimate"}
    missing  = required - set(scenario.keys())
    if missing:
        raise ValueError(f"optimize_reserves() — scenario missing keys: {missing}")

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

    replenishment_days = round(window_days * REPLENISHMENT_OVERHEAD_FACTOR, 1)

    drawdown_schedule = _build_drawdown_schedule(window_days)

    policy_recommendation = _build_policy_recommendation(
        scenario_type   = scenario_type,
        severity        = severity,
        supply_gap_pct  = supply_gap_pct,
        days_remaining  = days_remaining,
        window_days     = window_days,
        replenishment_days = replenishment_days,
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
