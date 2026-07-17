"""
Stage 1 — Data Collection Agent (stub)
Responsibility: load a raw signal from a fixture file.
In the vertical slice this simply reads fixtures/mock_signal.json.
"""
import json
import pathlib


FIXTURE_PATH = pathlib.Path(__file__).parent.parent.parent / "fixtures" / "mock_signal.json"


def load_mock_signal() -> dict:
    """Return the hardcoded mock raw_signal matching the §5 Stage 1 schema."""
    with open(FIXTURE_PATH, "r", encoding="utf-8") as fh:
        signal = json.load(fh)
    return signal
