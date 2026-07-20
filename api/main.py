"""
FastAPI app — Energy Supply Chain Resilience API
/api/main.py
"""

import json
import asyncio
import logging
import pathlib
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from db.supabase_client import supabase
from orchestrator.run_full_pipeline import run_pipeline, RUN_LOG_PATH
from agents.ingest_eia import fetch_eia_signals, fetch_crude_prices, fetch_supply_data
from agents.routing_advisor import assess_routes

app = FastAPI(
    title="Energy Supply Chain Resilience API",
    description="End-to-end ML pipeline for geopolitical supply chain risk.",
    version="1.0.0",
)

# Allow any localhost port — Vite picks 5173/5174/etc. depending on what's free.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── SSE broadcast queue (in-process; one server instance) ─────────────────
# Each connected client gets its own asyncio.Queue that receives events.
_sse_clients: list[asyncio.Queue] = []

def _broadcast_event(event: dict):
    """Push an event dict to every connected SSE client (sync-safe)."""
    dead = []
    for q in _sse_clients:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try:
            _sse_clients.remove(q)
        except ValueError:
            pass

# Expose broadcaster so run_full_pipeline can import it
import api.main as _self_module
_self_module.broadcast_event = _broadcast_event  # type: ignore

# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", summary="Health check")
def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}

@app.get("/api/risk-scores", summary="Get latest risk scores per corridor")
def get_risk_scores():
    resp = supabase.table("risk_scores").select("*").order("generated_at", desc=True).limit(50).execute()
    data = resp.data
    # Filter for the latest per corridor
    latest = {}
    for row in data:
        c = row["corridor"]
        if c not in latest:
            latest[c] = row
    return list(latest.values())

@app.get("/api/scenarios", summary="Get latest scenario per type")
def get_scenarios():
    resp = supabase.table("scenarios").select("*").order("generated_at", desc=True).limit(50).execute()
    data = resp.data
    latest = {}
    for row in data:
        t = row["scenario_type"]
        if t not in latest:
            latest[t] = row
    return list(latest.values())

@app.get("/api/procurement-recs", summary="Get ranked recommendations for a scenario")
def get_procurement_recs(scenario_id: str):
    resp = supabase.table("procurement_recs").select("*").eq("scenario_id", scenario_id).order("rank").execute()
    # Return empty list instead of 404 — dashboard handles empty gracefully
    return resp.data or []

@app.get("/api/reserve-plan", summary="Get reserve plan for a scenario")
def get_reserve_plan(scenario_id: str):
    resp = supabase.table("reserve_plans").select("*").eq("scenario_id", scenario_id).execute()
    # Return empty object instead of 404
    return resp.data[0] if resp.data else {}

@app.get("/api/pipeline-status", summary="Get latest pipeline run latency and status")
def get_pipeline_status():
    if not RUN_LOG_PATH.exists():
        # No runs yet — return a safe sentinel instead of 404
        return {"status": "no_runs_yet", "total_latency_seconds": None, "stage_timings": {}}
    with open(RUN_LOG_PATH, "r", encoding="utf-8") as f:
        runs = json.load(f)
    if not runs:
        return {"status": "no_runs_yet", "total_latency_seconds": None, "stage_timings": {}}
    return runs[0]

@app.get("/api/crude-oil", summary="Live crude oil prices and supply data from EIA")
def get_crude_oil():
    """
    Returns a snapshot of live EIA data:
      - Brent and WTI daily prices (last 30 days)
      - Today's prices + day-on-day % change
      - US crude inventory and refinery input (weekly)
    """
    _, snapshot = fetch_eia_signals()
    return snapshot


@app.post("/api/pipeline/simulate", summary="Run a fast in-process pipeline simulation (no external calls)")
def simulate_pipeline(event_callback=None):
    """
    Runs a deterministic mock pipeline using pre-seeded data.
    All 6 stages execute instantly with synthetic but realistic values.
    Safe to call repeatedly — does NOT write to Supabase.
    """
    import time, uuid
    from datetime import datetime, timezone

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    stage_timings = {}

    _broadcast_event({"type": "pipeline_start", "stage": None, "label": None,
                      "ts": started_at, "data": {"run_id": run_id, "mode": "simulate"}})

    stages = [
        ("stage_1", "Data Collection",       0.8,  {"signals_collected": 42, "eia_brent": 81.62, "eia_source": "eia_live"}),
        ("stage_2", "Signal Normalization",   0.4,  {"processed": 38}),
        ("stage_3", "Risk Intelligence",      1.2,  {"corridors_scored": 2}),
        ("stage_4", "Scenario Modeling",      0.6,  {"scenarios_run": 3}),
        ("stage_5", "Procurement Ranking",    0.5,  {"recs_generated": 5}),
        ("stage_6", "Reserve Optimization",   0.3,  {"days_cover": 9.5}),
    ]

    for stage_id, label, duration, data in stages:
        _broadcast_event({"type": "stage_start", "stage": stage_id, "label": label,
                          "ts": datetime.now(timezone.utc).isoformat(), "data": {}})
        time.sleep(duration)
        stage_timings[stage_id] = duration
        _broadcast_event({"type": "stage_done", "stage": stage_id, "label": label,
                          "ts": datetime.now(timezone.utc).isoformat(),
                          "data": {**data, "elapsed": round(duration, 2)}})

    total = sum(stage_timings.values())
    completed_at = datetime.now(timezone.utc).isoformat()
    _broadcast_event({"type": "pipeline_done", "stage": None, "label": None,
                      "ts": completed_at,
                      "data": {"run_id": run_id, "total_latency_seconds": round(total, 3), "mode": "simulate"}})

    return {
        "id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "stage_timings": stage_timings,
        "total_latency_seconds": round(total, 3),
        "status": "simulated",
        "mode": "simulate",
    }


class RouteAssessRequest(BaseModel):
    origin: str
    destination: str


@app.get("/api/route/ports", summary="List all available ports for route advisor")
def get_available_ports():
    """
    Returns the list of ports available for origin/destination selection in the
    Route Advisor UI, with id, name, coords, and region.
    """
    from agents.routing_advisor import PORTS
    return [
        {"id": pid, "name": info["name"], "coords": info["coords"], "region": info["region"]}
        for pid, info in PORTS.items()
    ]


@app.post("/api/route/assess", summary="Assess candidate shipping routes based on geopolitical risk and crude oil price")
def post_assess_route(req: RouteAssessRequest):
    """
    Evaluates candidate routes, calculates costs, fuel, and war-risk premiums,
    and returns recommendations with map coordinates and Gemini-generated rationale.
    """
    # 1. Fetch current risk scores from Supabase
    try:
        res = supabase.table("risk_scores").select("*").order("generated_at", desc=True).limit(10).execute()
        rows = res.data or []
    except Exception as e:
        logger.error(f"[API] Failed to fetch risk scores: {e}")
        rows = []

    # Map newest score per corridor (latest row per corridor)
    risks: dict[str, float] = {"hormuz": 0.35, "red_sea": 0.55}  # realistic defaults
    seen: set[str] = set()
    for r in rows:
        corr = r.get("corridor")
        if corr and corr not in seen:
            seen.add(corr)
            risks[corr] = float(r.get("risk_score", 0.35))

    # 2. Get live Brent crude price from EIA
    try:
        prices = fetch_crude_prices(days=2)
        brent = float(prices.get("brent", [{}])[0].get("price", 82.0))
    except Exception:
        brent = 82.0

    # 3. Assess routes
    try:
        report = assess_routes(req.origin, req.destination, risks, brent)
        return report
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))
    except Exception as err:
        logger.exception(f"[API] Route assessment failed")
        raise HTTPException(status_code=500, detail=f"Assess failed: {err}")


@app.post("/api/pipeline/run", summary="Trigger the full pipeline end-to-end")
def trigger_pipeline():
    # Synchronous run — broadcasts SSE events as each stage completes
    log_data = run_pipeline(event_callback=_broadcast_event)
    return log_data

@app.get("/api/pipeline/stream", summary="SSE stream of live pipeline stage events")
async def pipeline_stream(request: Request):
    """
    Server-Sent Events endpoint.
    Each message is a JSON object:
      { "type": "stage_start" | "stage_done" | "pipeline_start" | "pipeline_done" | "heartbeat",
        "stage": "stage_1" | ... | null,
        "label": "human-readable label",
        "ts": "ISO8601",
        "data": { ...extra... } }
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    _sse_clients.append(queue)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    payload = json.dumps(event)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat to keep connection alive
                    heartbeat = json.dumps({
                        "type": "heartbeat",
                        "ts": datetime.now(timezone.utc).isoformat()
                    })
                    yield f"data: {heartbeat}\n\n"
        finally:
            try:
                _sse_clients.remove(queue)
            except ValueError:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
