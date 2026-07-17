"""
Stage 2 — Data Processing Agent (stub)
Responsibility: normalize a raw_signal into a processed_signal shape.
Vertical slice: trivial hardcoded transform — no real NLP.

Input:  raw_signal  (§5 Stage 1 schema)
Output: processed_signal (§5 Stage 2 schema)
"""
import uuid


def process_signal(raw_signal: dict) -> dict:
    """
    Stub transform.  Maps raw_signal fields into the §5 Stage 2 schema.
    Real implementation would: tokenize headline, classify signal_type, compute severity.
    """
    return {
        "id": str(uuid.uuid4()),
        "corridor": raw_signal["corridor"],          # pass-through
        "signal_type": "news",                        # hardcoded for mock source
        "severity_hint": raw_signal["raw_payload"].get("severity_hint", 0.5),
        "text_summary": (
            raw_signal["raw_payload"].get("headline", "No headline")
        ),
        "timestamp": raw_signal["timestamp"],
    }
