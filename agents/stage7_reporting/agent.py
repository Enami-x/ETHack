"""
Stage 7 — Reporting Agent (stub)
Responsibility: compile stages 3-6 into a human-readable markdown report.
Vertical slice: simple f-string template — no LLM, no PDF rendering yet.

Input:  risk_score, scenario, procurement_rec, reserve_plan
Output: report row (§5 Stage 7 — stored in `reports` table)
"""
import uuid
from datetime import datetime, timezone


def compile_report(
    risk_score: dict,
    scenario: dict,
    procurement_rec: dict,
    reserve_plan: dict,
) -> dict:
    """
    Stub report compiler.  Produces a structured markdown body from upstream outputs.
    Real build: Claude Sonnet generates executive prose; PDF export via WeasyPrint.
    """
    body = f"""# Energy Supply Chain Risk Report
*Generated: {datetime.now(timezone.utc).isoformat()}*
*Source: MOCK vertical slice — not for production use*

---

## Risk Assessment — {risk_score['corridor'].upper()} corridor
- **Risk Score:** {risk_score['risk_score']} (confidence {risk_score['confidence']})
- **Explanation:** {risk_score['explanation']}
- **Contributing Signals:** {', '.join(risk_score['contributing_signals'])}

---

## Active Scenario — {scenario['scenario_type']}
- **Severity:** {scenario['severity']}
- **Supply Gap:** {scenario['supply_gap_pct']}%
- **Price Impact:** {scenario['price_impact_pct']}%
- **Refinery Utilisation Impact:** {scenario['refinery_utilization_impact_pct']}%
- **Estimated SPR Days Remaining:** {scenario['spr_days_remaining_estimate']}

### Assumptions
{chr(10).join(f'- {a}' for a in scenario['assumptions'])}

---

## Procurement Recommendation (Rank #{procurement_rec['rank']})
- **Supplier:** {procurement_rec['supplier']}
- **Route:** {procurement_rec['route']}
- **Spot Price Estimate:** USD {procurement_rec['spot_price_est']:.2f}/bbl
- **Transit Time:** {procurement_rec['transit_time_days']} days
- **Refinery Compatibility:** {procurement_rec['refinery_compatibility_score']}
- **Overall Score:** {procurement_rec['overall_score']}
- **Rationale:** {procurement_rec['rationale']}

---

## Reserve Drawdown Plan
- **Days of Cover Remaining:** {reserve_plan['days_of_cover_remaining']}
- **Replenishment Window Estimate:** {reserve_plan['replenishment_window_estimate_days']} days
- **Policy Recommendation:** {reserve_plan['policy_recommendation']}

### Drawdown Schedule
| Day | Draw % |
|-----|--------|
{chr(10).join(f"| {d['day']} | {d['draw_pct']}% |" for d in reserve_plan['drawdown_schedule'])}
"""

    return {
        "id": str(uuid.uuid4()),
        "scenario_id": scenario["id"],
        "risk_score_id": risk_score["id"],
        "title": f"Risk Report — {scenario['scenario_type']} (MOCK)",
        "body_markdown": body,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
