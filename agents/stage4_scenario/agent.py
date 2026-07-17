"""
Stage 4 — Scenario Modeling Agent (stub)
Responsibility: simulate a named disruption event and compute cascading impacts.
Vertical slice: hardcoded hormuz_partial_closure scenario — no parametric formula yet.

Input:  risk_score row  (§5 Stage 3 schema)
Output: scenario row    (§5 Stage 4 schema)

NOTE: All numeric outputs are placeholder stubs.
Real build: parametric formula in code comments (per ARCHITECTURE.md §5 Stage 4 build note).
"""
import uuid
from datetime import datetime, timezone


def model_scenario(risk_score: dict) -> dict:
    """
    Stub scenario.
    Real formula (to be documented here):
        supply_gap_pct = base_gap * severity * corridor_dependency_factor
        price_impact_pct = supply_gap_pct * price_elasticity_coefficient
        refinery_utilization_impact_pct = supply_gap_pct * refinery_import_share
        spr_days_remaining = current_spr_mb / (daily_consumption_mb - supply_gap_mb)
    """
    return {
        "id": str(uuid.uuid4()),
        "scenario_type": "hormuz_partial_closure",   # hardcoded for mock
        "severity": risk_score["risk_score"],         # inherit from upstream score
        "supply_gap_pct": 18.0,                       # STUB: ~18% global oil transits Hormuz
        "price_impact_pct": 27.0,                     # STUB: rough price spike estimate
        "refinery_utilization_impact_pct": -12.0,     # STUB: negative = utilization drop
        "spr_days_remaining_estimate": 42.0,          # STUB: ~42 days US SPR cover
        "assumptions": [
            "STUB: 18% of global seaborne oil transits Strait of Hormuz (IEA 2024 baseline)",
            "STUB: Partial closure = 40% throughput reduction assumed",
            "STUB: Price elasticity coefficient = 1.5 (short-run)",
            "STUB: US SPR at ~350 MB, daily consumption ~20 MB/day",
            "STUB: No alternative routing assumed in this scenario (Cape of Good Hope adds 15 days)",
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
