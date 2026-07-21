"""
/config/assumptions.py
======================
Single source of truth for the modelling assumptions behind Stage 4 (scenario
modeling) and Stage 6 (reserve optimization). Previously these were hardcoded
literals scattered across scenario_modeling.py and reserve_optimizer.py; several
were stale. They now live here — each with a source citation and a LAST_UPDATED
date — and both stages READ from this module (Task 6).

Design philosophy (unchanged): every number is a named, commented, TESTABLE
constant. No black boxes. The dashboard surfaces this whole block verbatim via the
/api/assumptions endpoint (see get_assumptions_block()) so the assumptions driving
every number are visible and challengeable.

To recalibrate the model, edit the values here and bump the per-value last_updated.
"""

from datetime import date

# Global "as of" date for this assumptions set. Bump when any value below changes.
LAST_UPDATED: str = "2026-07-21"


# =============================================================================
# CORRIDOR EXPOSURE — fraction of India's crude imports exposed per corridor
# =============================================================================

# Fraction of India's crude imports that transit the Strait of Hormuz.
# UPDATED 2026: India now routes ~70% of crude imports OUTSIDE Hormuz — Russian
# Urals (via Cape/Suez, not Hormuz), plus US, West African, and Latin American
# barrels across the Atlantic/Indian Ocean. That leaves ~30% transiting Hormuz,
# down from the ~45% figure in the original problem statement.
# Source: 2025–2026 India crude import mix (Russia ~35–40%, Middle East Gulf ~30%,
#         Americas/W.Africa balance); trade-flow reporting (Kpler/Vortexa-class).
# last_updated: 2026-07-21  (was 0.45)
HORMUZ_INDIA_SHARE: float = 0.30

# Fraction of India's crude imports affected by a full Red Sea suspension.
# Mechanism differs from Hormuz: Red Sea closure forces Cape of Good Hope rerouting
# (+10–14 days transit) rather than outright volume loss. Direct crude volume share
# affected is small (mostly West/North African crude via Suez; Gulf crude uses Hormuz).
# Source: Assumption; documented as a testable parameter.
# last_updated: 2026-07-21
RED_SEA_INDIA_CRUDE_SHARE: float = 0.15

# Effective India impact of an OPEC+ emergency cut, as a fraction of severity.
# India sources ~65% of crude from OPEC+ (BP Statistical Review), but emergency cuts
# hit spot/margin barrels first and long-term contracts buffer the first tranche —
# so effective near-term India impact is modelled at 25% of severity (conservative).
# last_updated: 2026-07-21
OPEC_CUT_INDIA_EFFECTIVE_SHARE: float = 0.25


# =============================================================================
# STRATEGIC RESERVE / NATIONAL BUFFER
# =============================================================================

# India's strategic petroleum reserve (SPR) cover AT FULL CAPACITY, in days of
# crude-import equivalent. This is the strategic reserve ONLY (not commercial stock).
# Source: India SPR Phase-I capacity ≈ 5.33 MMT ≈ ~9.5 days of imports at full fill.
# last_updated: 2026-07-21
SPR_STRATEGIC_DAYS_AT_FULL: float = 9.5

# Current SPR fill fraction. The SPR is NOT full — it sits around ~64% filled.
# Source: 2025–2026 SPR fill status reporting.
# last_updated: 2026-07-21
SPR_CURRENT_FILL_PCT: float = 0.64

# Total national crude buffer INCLUDING commercial/refiner stock, in days. This is
# the fuller resilience picture (strategic + commercial). Surfaced as context in the
# dashboard; NOT the figure the SPR-drawdown math runs on (see SPR_BASELINE_DAYS).
# Source: India total stock cover (strategic + industry) ≈ 74 days.
# last_updated: 2026-07-21
TOTAL_NATIONAL_BUFFER_DAYS: float = 74.0

# SPR baseline the SCENARIO + RESERVE math actually runs on = strategic reserve
# actually on hand today = full-capacity days × current fill. reserve_optimizer models
# the *strategic* reserve narrowly (that is what "SPR" means), so it draws down what is
# actually stored, not the full-capacity or total-buffer figure.
#   9.5 × 0.64 ≈ 6.08 days.
# last_updated: 2026-07-21  (was a flat 9.5)
SPR_BASELINE_DAYS: float = round(SPR_STRATEGIC_DAYS_AT_FULL * SPR_CURRENT_FILL_PCT, 2)

# SPR-days policy thresholds (Stage 6). Rescaled from the old 5.0 / 8.0 (which were
# tuned to a 9.5-day baseline) by the current fill fraction, so the CRITICAL/CAUTION/
# STABLE bands stay meaningful against the ~6.08-day effective baseline.
#   CRITICAL was 5.0 → 5.0 × 0.64 ≈ 3.2 ;  CAUTION was 8.0 → 8.0 × 0.64 ≈ 5.1
# last_updated: 2026-07-21
SPR_DAYS_CRITICAL: float = round(5.0 * SPR_CURRENT_FILL_PCT, 1)  # ≈ 3.2
SPR_DAYS_CAUTION:  float = round(8.0 * SPR_CURRENT_FILL_PCT, 1)  # ≈ 5.1


# =============================================================================
# CONSUMPTION
# =============================================================================

# India's daily crude consumption / refinery throughput, in million barrels/day.
# Used to convert supply-gap fractions into absolute volumes where needed.
# Source: India refinery crude runs ≈ 5.3–5.4 mb/d (2025–2026). TESTABLE.
# last_updated: 2026-07-21
INDIA_DAILY_CRUDE_CONSUMPTION_MBD: float = 5.4


# =============================================================================
# SCENARIO ELASTICITY / OFFSET MULTIPLIERS
# (mechanism rationale documented in scenario_modeling.py section headers)
# =============================================================================

# Price elasticity multipliers (price impact per unit of supply gap), per scenario.
HORMUZ_PRICE_ELASTICITY:  float = 1.8   # panic premium on chokepoint closure fears
OPEC_PRICE_ELASTICITY:    float = 2.2   # cartel pricing power > logistics disruption
RED_SEA_PRICE_ELASTICITY: float = 1.3   # freight-dominated, rerouting absorbs impact

# Refinery-utilisation offset multipliers (utilisation hit per unit of supply gap).
HORMUZ_REFINERY_OFFSET:  float = 0.9    # limited short-term substitution
OPEC_REFINERY_OFFSET:    float = 0.6    # more lead time; spot from non-OPEC+
RED_SEA_REFINERY_OFFSET: float = 0.4    # cargo mostly arrives via Cape eventually


# =============================================================================
# PROCUREMENT (Stage 6 lead-time model — Task 8)
# =============================================================================

# Assumed lead time for alternate procurement (Stage 5 suppliers) to actually deliver
# barrels after a disruption begins: contract execution + voyage time before the first
# replacement cargo lands. Until then the SPR bears the full supply gap. TESTABLE.
# Source: Assumption — reroute/contract + long-haul voyage (e.g. US ~45d, Brazil ~40d).
# last_updated: 2026-07-21
PROCUREMENT_LEAD_TIME_DAYS: int = 10


# =============================================================================
# UI-FACING ASSUMPTIONS BLOCK
# =============================================================================

def get_assumptions_block() -> dict:
    """
    Return the full assumptions set as a structured, dashboard-ready block:
    each entry has a value, unit, human label, source, and last_updated. Served by
    GET /api/assumptions and embedded (compactly) in each scenario's `detail`.
    """
    return {
        "last_updated": LAST_UPDATED,
        "assumptions": [
            {
                "key": "hormuz_india_share", "value": HORMUZ_INDIA_SHARE, "unit": "fraction",
                "label": "Share of India's crude transiting the Strait of Hormuz",
                "source": "2025–2026 import mix: ~70% now routed outside Hormuz (Russia + Americas + W.Africa).",
                "last_updated": "2026-07-21", "previous": 0.45,
            },
            {
                "key": "red_sea_india_crude_share", "value": RED_SEA_INDIA_CRUDE_SHARE, "unit": "fraction",
                "label": "Share of India's crude exposed to a Red Sea suspension",
                "source": "Assumption; mainly W/N African crude via Suez. Mechanism is rerouting, not volume loss.",
                "last_updated": "2026-07-21",
            },
            {
                "key": "opec_cut_india_effective_share", "value": OPEC_CUT_INDIA_EFFECTIVE_SHARE, "unit": "fraction",
                "label": "Effective India impact of an OPEC+ emergency cut (× severity)",
                "source": "~65% India crude from OPEC+, but cuts hit spot/margin barrels first; 25% effective.",
                "last_updated": "2026-07-21",
            },
            {
                "key": "spr_baseline_days", "value": SPR_BASELINE_DAYS, "unit": "days",
                "label": "SPR baseline used by the drawdown math (strategic reserve on hand)",
                "source": "9.5 days at full capacity × 64% current fill ≈ 6.08 days.",
                "last_updated": "2026-07-21", "previous": 9.5,
            },
            {
                "key": "spr_strategic_days_at_full", "value": SPR_STRATEGIC_DAYS_AT_FULL, "unit": "days",
                "label": "SPR cover at FULL capacity (context)",
                "source": "India SPR Phase-I ≈ 5.33 MMT ≈ ~9.5 days of imports at full fill.",
                "last_updated": "2026-07-21",
            },
            {
                "key": "spr_current_fill_pct", "value": SPR_CURRENT_FILL_PCT, "unit": "fraction",
                "label": "Current SPR fill level",
                "source": "2025–2026 SPR fill status.",
                "last_updated": "2026-07-21",
            },
            {
                "key": "total_national_buffer_days", "value": TOTAL_NATIONAL_BUFFER_DAYS, "unit": "days",
                "label": "Total national buffer incl. commercial stock (context)",
                "source": "Strategic + industry stock cover ≈ 74 days.",
                "last_updated": "2026-07-21",
            },
            {
                "key": "india_daily_crude_consumption_mbd", "value": INDIA_DAILY_CRUDE_CONSUMPTION_MBD, "unit": "mb/d",
                "label": "India daily crude throughput",
                "source": "India refinery crude runs ≈ 5.3–5.4 mb/d (2025–2026).",
                "last_updated": "2026-07-21",
            },
            {
                "key": "procurement_lead_time_days", "value": PROCUREMENT_LEAD_TIME_DAYS, "unit": "days",
                "label": "Lead time for alternate procurement to deliver",
                "source": "Assumption: contract execution + long-haul voyage before first replacement cargo lands.",
                "last_updated": "2026-07-21",
            },
        ],
        "elasticity_multipliers": {
            "hormuz_price_elasticity":  HORMUZ_PRICE_ELASTICITY,
            "opec_price_elasticity":    OPEC_PRICE_ELASTICITY,
            "red_sea_price_elasticity": RED_SEA_PRICE_ELASTICITY,
            "hormuz_refinery_offset":   HORMUZ_REFINERY_OFFSET,
            "opec_refinery_offset":     OPEC_REFINERY_OFFSET,
            "red_sea_refinery_offset":  RED_SEA_REFINERY_OFFSET,
        },
        "policy_thresholds": {
            "spr_days_critical": SPR_DAYS_CRITICAL,
            "spr_days_caution":  SPR_DAYS_CAUTION,
        },
    }
