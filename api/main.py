"""
FastAPI app — Energy Supply Chain Resilience API
/api/main.py

Endpoints
---------
GET /              — health check
GET /pipeline/latest — run the full vertical slice pipeline and return all 6 tables as JSON

Usage:
    uvicorn api.main:app --reload --port 8000
    # then visit http://localhost:8000/pipeline/latest
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

# Re-use the pipeline logic (it's pure Python, no side effects)
from run_vertical_slice import run_pipeline, STATE


app = FastAPI(
    title="Energy Supply Chain Resilience API",
    description=(
        "Vertical slice — mocked pipeline. "
        "All data is hardcoded; no external services are called."
    ),
    version="0.1.0",
)


@app.get("/", summary="Health check")
def health() -> dict:
    return {"status": "ok", "version": "0.1.0", "mode": "vertical_slice_mock"}


@app.get(
    "/pipeline/latest",
    summary="Run pipeline and return latest state of all 6 tables",
    response_class=JSONResponse,
)
def pipeline_latest() -> dict:
    """
    Runs the full mocked pipeline end-to-end and returns the final in-memory state
    as JSON — matching the 6 Supabase table schemas from ARCHITECTURE.md §5.

    Tables returned:
        raw_signals, processed_signals, risk_scores,
        scenarios, procurement_recs, reserve_plans, reports
    """
    state = run_pipeline()
    return JSONResponse(content=state)
