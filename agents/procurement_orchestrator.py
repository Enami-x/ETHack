"""
/agents/procurement_orchestrator.py
=====================================
Stage 5 — Procurement Orchestrator

Responsibility:
    Rank alternative crude suppliers/routes given an active Stage 4 scenario.
    Applies a transparent weighted scoring formula that PENALISES suppliers whose
    corridor_dependency overlaps with the disrupted corridor — so Saudi Arabia and
    UAE rank lower during a Hormuz scenario even though their base metrics are strong.

Formula (all weights are named constants — inspectable by judges):
    overall_score = (
        WEIGHTS["price"]         * price_score       +  # inverted/normalised
        WEIGHTS["transit_time"]  * transit_score     +  # inverted/normalised
        WEIGHTS["compatibility"] * compat_score      +
        WEIGHTS["corridor_safety"] * corridor_score  +  # 1.0 - corridor_penalty
        WEIGHTS["relationship"]  * relationship_score
    )

Corridor penalty logic:
    If a supplier's corridor_dependency includes the affected corridor, it receives
    a penalty proportional to the scenario's severity:
        corridor_penalty = severity * CORRIDOR_PENALTY_SCALE
    If not exposed, corridor_score = 1.0 (no penalty).

Usage:
    from agents.procurement_orchestrator import rank_suppliers
    ranked = rank_suppliers(scenario, suppliers)
"""

import pathlib
import logging
from datetime import datetime, timezone
import uuid

logger = logging.getLogger(__name__)


# =============================================================================
# SCORING WEIGHTS — named constants, all values sum to 1.0.
# Justification documented inline.
# =============================================================================
WEIGHTS: dict[str, float] = {
    # Lower price = better. 0.30 weight: cost is important but not the only criterion.
    # In a crisis, reliability and corridor safety outweigh spot price optimisation.
    "price":           0.30,

    # Shorter transit = better. 0.15 weight: transit time affects inventory buffer.
    # Lower weight than price — most Indian refineries have 15–30 day buffer stock.
    "transit_time":    0.15,

    # Higher refinery compatibility = better. 0.25 weight: switching crude grades
    # mid-disruption carries real operational risk (yield changes, desulphurisation
    # load, equipment calibration). A high-compatibility source reduces switching costs.
    "compatibility":   0.25,

    # 1.0 - penalty if supplier transits the affected corridor. 0.25 weight: the
    # whole point of procurement diversification in a disruption scenario is to
    # source AROUND the affected corridor. Equally weighted with compatibility.
    "corridor_safety": 0.25,

    # Existing relationship bonus. 0.05 weight: small but real — established
    # trading relationships mean contracts are in place, payment rails work,
    # and credit lines exist. Matters for execution speed under crisis conditions.
    "relationship":    0.05,
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "WEIGHTS must sum to 1.0"

# -----------------------------------------------------------------------------
# TWO PENALTY TYPES (Task 7) — a single linear corridor penalty conflated two very
# different disruption mechanisms. They are now distinct:
#
#   AVAILABILITY penalty — the disrupted corridor makes the supplier's volume
#     physically UNAVAILABLE (a Hormuz closure strands Gulf export terminals). This
#     is severe: at severity 1.0 an exposed supplier loses essentially all corridor
#     safety, because the barrels simply cannot sail.
#
#   COST/DELAY penalty — the disruption does NOT strand volume but forces a costlier,
#     slower reroute (a Red Sea suspension pushes cargo around the Cape of Good Hope,
#     +10–14 days, +freight). The supplier is still usable, just degraded — so the
#     penalty is materially smaller than an availability loss.
#
# Which penalty applies is chosen by the scenario's disruption MECHANISM, not by a
# one-size scale. Both are named, testable constants.
AVAILABILITY_PENALTY_SCALE: float = 1.0   # exposed volume lost at severity 1.0
COST_DELAY_PENALTY_SCALE:   float = 0.5   # exposed volume merely rerouted/pricier

# Back-compat alias (older callers referenced a single CORRIDOR_PENALTY_SCALE).
CORRIDOR_PENALTY_SCALE: float = AVAILABILITY_PENALTY_SCALE

# Map from scenario_type to which corridors are affected.
SCENARIO_CORRIDOR_MAP: dict[str, list[str]] = {
    "hormuz_partial_closure": ["hormuz"],
    "opec_emergency_cut":     [],           # not corridor-specific; affects all routes
    "red_sea_suspension":     ["red_sea"],
}

# Disruption MECHANISM per scenario_type — selects which penalty type applies.
#   "availability" → exposed supplier volume is lost (severe penalty)
#   "cost_delay"   → exposed supplier volume is rerouted, slower/pricier (mild penalty)
SCENARIO_MECHANISM: dict[str, str] = {
    "hormuz_partial_closure": "availability",  # Gulf terminals stranded → volume loss
    "red_sea_suspension":     "cost_delay",    # Cape rerouting → delay + freight cost
    "opec_emergency_cut":     "availability",  # supply-side volume loss (no corridor)
}
DEFAULT_MECHANISM: str = "availability"


# =============================================================================
# SCORING HELPERS
# =============================================================================

def _normalise_lower_better(value: float, min_val: float, max_val: float) -> float:
    """
    Normalise a value to [0, 1] where LOWER original value → HIGHER score.
    Used for price and transit_time (both: lower = better).
    Clamps to [0, 1] to handle out-of-range inputs gracefully.
    """
    if max_val == min_val:
        return 1.0
    score = 1.0 - (value - min_val) / (max_val - min_val)
    return max(0.0, min(1.0, round(score, 4)))


def _corridor_penalty(
    supplier: dict,
    affected_corridors: list[str],
    severity: float,
    mechanism: str,
) -> tuple[float, str]:
    """
    Return (penalty, penalty_type) based on whether this supplier's corridor_dependency
    overlaps the affected corridors AND the scenario's disruption mechanism (Task 7).

      not exposed              → (0.0, "none")
      exposed, availability    → (severity × AVAILABILITY_PENALTY_SCALE, "availability")
      exposed, cost_delay      → (severity × COST_DELAY_PENALTY_SCALE,   "cost_delay")

    The availability penalty models stranded volume (severe); the cost/delay penalty
    models a costlier/slower reroute (mild). Penalty is clamped to [0, 1].
    """
    dep = supplier.get("corridor_dependency", [])
    if not dep:           # explicit empty list → no corridor exposure
        return 0.0, "none"
    exposed = any(c in affected_corridors for c in dep)
    if not exposed:
        return 0.0, "none"

    if mechanism == "cost_delay":
        scale, ptype = COST_DELAY_PENALTY_SCALE, "cost_delay"
    else:  # "availability" (default)
        scale, ptype = AVAILABILITY_PENALTY_SCALE, "availability"
    return round(min(1.0, severity * scale), 4), ptype


def _route_description(supplier: dict, affected_corridors: list[str]) -> str:
    """Generate a compact route string for the procurement_recs row."""
    dep = supplier.get("corridor_dependency", [])
    if not dep:
        return f"{supplier['supplier']} → India (no Hormuz/Red Sea exposure)"
    dep_str = " + ".join(c.replace("_", " ").title() for c in dep)
    exposed = any(c in affected_corridors for c in dep)
    flag = " ⚠ DISRUPTED CORRIDOR" if exposed else ""
    return f"{supplier['supplier']} → India via {dep_str}{flag}"


# =============================================================================
# PUBLIC API
# =============================================================================

def rank_suppliers(scenario: dict, suppliers: list[dict]) -> list[dict]:
    """
    Rank alternative crude suppliers given an active Stage 4 scenario.

    Args:
        scenario:  A Stage 4 run_scenario() output dict (or a Supabase scenarios row).
                   Must contain: scenario_type, severity (float 0–1).
        suppliers: List of supplier dicts from fixtures/suppliers.json.

    Returns:
        List of procurement_recs dicts (§5 Stage 5 schema), sorted by rank ascending.
        Each dict contains:
          id, scenario_id, rank, supplier, route, spot_price_est, transit_time_days,
          refinery_compatibility_score, overall_score, rationale, source, generated_at

    Raises:
        ValueError: if scenario or suppliers are invalid/empty.
    """
    if not suppliers:
        raise ValueError("rank_suppliers() requires at least one supplier.")

    scenario_type = scenario.get("scenario_type", "")
    severity      = float(scenario.get("severity", 0.0))
    scenario_id   = scenario.get("id")  # may be None if scenario wasn't DB-persisted

    affected_corridors = SCENARIO_CORRIDOR_MAP.get(scenario_type, [])
    mechanism          = SCENARIO_MECHANISM.get(scenario_type, DEFAULT_MECHANISM)

    # -------------------------------------------------------------------------
    # Compute normalisation ranges across the supplier pool
    # -------------------------------------------------------------------------
    prices   = [s["typical_spot_price_usd_bbl"] for s in suppliers]
    transits = [s["typical_transit_time_days"] for s in suppliers]
    min_price, max_price     = min(prices), max(prices)
    min_transit, max_transit = min(transits), max(transits)

    # -------------------------------------------------------------------------
    # Score each supplier
    # -------------------------------------------------------------------------
    scored: list[dict] = []
    for sup in suppliers:
        price_score   = _normalise_lower_better(
            sup["typical_spot_price_usd_bbl"], min_price, max_price
        )
        transit_score = _normalise_lower_better(
            sup["typical_transit_time_days"], min_transit, max_transit
        )
        compat_score  = float(sup["refinery_compatibility_score"])
        rel_score     = 1.0 if sup.get("existing_relationship") else 0.0
        penalty, penalty_type = _corridor_penalty(
            sup, affected_corridors, severity, mechanism
        )
        corridor_score = round(1.0 - penalty, 4)

        overall = round(
            WEIGHTS["price"]           * price_score
            + WEIGHTS["transit_time"]  * transit_score
            + WEIGHTS["compatibility"] * compat_score
            + WEIGHTS["corridor_safety"] * corridor_score
            + WEIGHTS["relationship"]  * rel_score,
            4,
        )

        scored.append({
            "_supplier_data":    sup,
            "_price_score":      price_score,
            "_transit_score":    transit_score,
            "_compat_score":     compat_score,
            "_corridor_score":   corridor_score,
            "_corridor_penalty": penalty,
            "_penalty_type":     penalty_type,
            "_rel_score":        rel_score,
            "overall_score":     overall,
        })

    # Sort descending by overall_score, then ascending by price as tiebreaker
    scored.sort(key=lambda x: (-x["overall_score"], x["_supplier_data"]["typical_spot_price_usd_bbl"]))

    # -------------------------------------------------------------------------
    # Build output rows
    # -------------------------------------------------------------------------
    now = datetime.now(timezone.utc).isoformat()
    results: list[dict] = []

    for rank_idx, item in enumerate(scored, start=1):
        sup          = item["_supplier_data"]
        penalty      = item["_corridor_penalty"]
        penalty_type = item["_penalty_type"]
        overall      = item["overall_score"]
        corridor_sc  = item["_corridor_score"]

        route = _route_description(sup, affected_corridors)

        # Template-based rationale — explicit, no LLM needed here. The clause names the
        # DISRUPTION MECHANISM (availability loss vs cost/delay reroute) so the two
        # penalty types are visible, not conflated (Task 7).
        if penalty > 0.0 and penalty_type == "availability":
            scale = AVAILABILITY_PENALTY_SCALE
            penalty_clause = (
                f" HOWEVER, {sup['supplier']} is {affected_corridors[0].replace('_',' ').title()}-dependent, "
                f"and this scenario STRANDS that volume (availability loss): AVAILABILITY penalty "
                f"{penalty:.2f} (severity {severity:.1f} × {scale}× scale), cutting corridor_safety to "
                f"{corridor_sc:.2f} — these barrels cannot sail while the corridor is closed."
            )
        elif penalty > 0.0 and penalty_type == "cost_delay":
            scale = COST_DELAY_PENALTY_SCALE
            penalty_clause = (
                f" NOTE: {sup['supplier']} is {affected_corridors[0].replace('_',' ').title()}-dependent, but "
                f"this scenario REROUTES rather than strands the volume: COST/DELAY penalty "
                f"{penalty:.2f} (severity {severity:.1f} × {scale}× scale), softening corridor_safety to "
                f"{corridor_sc:.2f} — cargo still arrives via a longer, costlier route (e.g. Cape of Good Hope)."
            )
        else:
            penalty_clause = (
                f" {sup['supplier']} has zero exposure to the disrupted corridor(s) — no penalty applied."
            )
        rel_clause = (
            " Existing trading relationship enables faster contract execution."
            if sup.get("existing_relationship")
            else " No existing trading relationship — contract setup time required."
        )
        rationale = (
            f"Ranked #{rank_idx}: {sup['supplier']} ({sup['crude_grade']}) — "
            f"overall_score={overall:.4f}. "
            f"Refinery compatibility {sup['refinery_compatibility_score']:.2f}/1.00. "
            f"Spot ~${sup['typical_spot_price_usd_bbl']:.2f}/bbl, "
            f"transit ~{sup['typical_transit_time_days']} days."
            f"{penalty_clause}"
            f"{rel_clause}"
            f" {sup['notes'][:120]}..."
        )

        row = {
            "id":                           str(uuid.uuid4()),
            "scenario_id":                  scenario_id,
            "rank":                         rank_idx,
            "supplier":                     sup["supplier"],
            "route":                        route,
            "spot_price_est":               sup["typical_spot_price_usd_bbl"],
            "transit_time_days":            float(sup["typical_transit_time_days"]),
            "refinery_compatibility_score": sup["refinery_compatibility_score"],
            "overall_score":                overall,
            "rationale":                    rationale,
            "source":                       "mock",   # fixture-based supplier data
            "generated_at":                 now,
        }
        results.append(row)

    return results
