"""
FastAPI app — Energy Supply Chain Resilience API
/api/main.py
"""

import json
import pathlib
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from db.supabase_client import supabase
from orchestrator.run_full_pipeline import run_pipeline, RUN_LOG_PATH

app = FastAPI(
    title="Energy Supply Chain Resilience API",
    description="End-to-end ML pipeline for geopolitical supply chain risk.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for hackathon deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    if not resp.data:
        raise HTTPException(status_code=404, detail="No recommendations found for this scenario")
    return resp.data

@app.get("/api/reserve-plan", summary="Get reserve plan for a scenario")
def get_reserve_plan(scenario_id: str):
    resp = supabase.table("reserve_plans").select("*").eq("scenario_id", scenario_id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="No reserve plan found for this scenario")
    return resp.data[0]

@app.get("/api/pipeline-status", summary="Get latest pipeline run latency and status")
def get_pipeline_status():
    if not RUN_LOG_PATH.exists():
        raise HTTPException(status_code=404, detail="No pipeline runs recorded yet")
    with open(RUN_LOG_PATH, "r", encoding="utf-8") as f:
        runs = json.load(f)
    if not runs:
        raise HTTPException(status_code=404, detail="No pipeline runs recorded yet")
    return runs[0]

@app.post("/api/pipeline/run", summary="Trigger the full pipeline end-to-end")
def trigger_pipeline():
    # Synchronous for the hackathon as requested
    log_data = run_pipeline()
    return log_data
