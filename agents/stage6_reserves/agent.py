"""
Stage 6 — Reserve Optimization Agent (stub)
Responsibility: model SPR drawdown against the active scenario's supply gap.
Vertical slice: hardcoded 7-day schedule — no drawdown formula yet.

Input:  scenario row        (§5 Stage 4 schema)
Output: reserve_plan row    (§5 Stage 6 schema)
"""
import uuid
from datetime import datetime, timezone


def optimize_reserves(scenario: dict) -> dict:
    """
    Stub reserve plan.
    Real build: drawdown formula:
        daily_draw_mb = supply_gap_mb / drawdown_days
        draw_pct[day] = daily_draw_mb / total_spr_mb * 100
        days_of_cover_remaining = total_spr_mb / daily_consumption_mb
    """
    # Stub: 7-day schedule, flat 2% per day draw
    drawdown_schedule = [
        {"day": d, "draw_pct": 2.0} for d in range(1, 8)
    ]

    return {
        "id": str(uuid.uuid4()),
        "scenario_id": scenario["id"],
        "drawdown_schedule": drawdown_schedule,            # STUB: 7-day flat 2%/day
        "days_of_cover_remaining": scenario["spr_days_remaining_estimate"],  # inherit
        "replenishment_window_estimate_days": 90.0,        # STUB
        "policy_recommendation": (
            "[MOCK] Initiate coordinated IEA emergency release at 2% SPR/day for 7 days "
            "while Cape of Good Hope re-routing comes online (~28-day lead time). "
            "Real build will compute optimal drawdown curve minimising price volatility."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
