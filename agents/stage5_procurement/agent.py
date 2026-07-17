"""
Stage 5 — Procurement Agent (stub)
Responsibility: rank alternative crude sources/routes given the active scenario.
Vertical slice: one hardcoded recommendation — no real supplier DB or LLM yet.

Input:  scenario row        (§5 Stage 4 schema)
Output: procurement_rec row (§5 Stage 5 schema)
"""
import uuid
from datetime import datetime, timezone


def recommend_procurement(scenario: dict) -> dict:
    """
    Stub procurement recommendation.
    Real build: score supplier database (fixture) across:
        - spot_price_est (from EIA / price feed)
        - transit_time_days (from AIS / routing DB)
        - refinery_compatibility_score (from refinery specs fixture)
        - geopolitical_risk (from Stage 3 risk_scores for that corridor)
    Then rank by weighted overall_score and generate rationale via Claude Sonnet.
    """
    return {
        "id": str(uuid.uuid4()),
        "scenario_id": scenario["id"],
        "rank": 1,
        "supplier": "Saudi Aramco (West Texas Intermediate substitute)",   # STUB
        "route": "Ras Tanura → Cape of Good Hope → Rotterdam",            # STUB
        "spot_price_est": 92.50,          # STUB USD/barrel
        "transit_time_days": 28.0,        # STUB via Cape of Good Hope
        "refinery_compatibility_score": 0.88,  # STUB 0–1
        "overall_score": 0.79,            # STUB weighted composite
        "rationale": (
            "[MOCK] Cape of Good Hope re-routing avoids Hormuz entirely. "
            "Saudi Aramco medium-sweet crude is compatible with Rotterdam refinery slate. "
            "Real build will generate this text via Claude Sonnet."
        ),
        "source": "mock",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
