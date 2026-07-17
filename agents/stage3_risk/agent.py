"""
Stage 3 — Risk Intelligence Agent (stub)
Responsibility: produce a risk_score row per corridor/supplier.
Vertical slice: hardcoded score — no weighted formula yet.

Input:  processed_signal (§5 Stage 2 schema)
Output: risk_score row   (§5 Stage 3 schema)

NOTE: risk_score = 0.72, confidence = 0.65 are placeholder constants.
Real build: transparent weighted formula documented in code comments.
"""
import uuid
from datetime import datetime, timezone


def score_risk(processed_signal: dict) -> dict:
    """
    Stub scoring.
    Real implementation will apply a transparent weighted formula:
        risk_score = w1*severity + w2*source_credibility + w3*recency_decay
    """
    return {
        "id": str(uuid.uuid4()),
        "corridor": processed_signal["corridor"],
        "supplier": None,                             # no supplier-level data in mock
        "risk_score": 0.72,                           # STUB constant
        "confidence": 0.65,                           # STUB constant
        "explanation": (
            "[MOCK] Stub explanation — real build will use Claude Sonnet "
            "to generate a natural-language rationale from the contributing signals."
        ),
        "contributing_signals": [processed_signal["id"]],
        "source": "mock",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
