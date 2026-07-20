import json
import logging
import time
import uuid
import pathlib
from datetime import datetime, timezone
from typing import Callable, Optional

from db.supabase_client import supabase

from agents.ingest_ofac import fetch_ofac_signals
from agents.ingest_rss import fetch_rss_signals
from agents.ingest_eia import fetch_eia_signals
from agents.normalize_signals import normalize_signals
from agents.risk_intelligence import compute_risk_score
from agents.scenario_modeling import run_scenario
from agents.procurement_orchestrator import rank_suppliers
from agents.reserve_optimizer import optimize_reserves

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

STAGE_LABELS = {
    "stage_1": "Data Collection",
    "stage_2": "Signal Normalization",
    "stage_3": "Risk Intelligence",
    "stage_4": "Scenario Modeling",
    "stage_5": "Procurement Ranking",
    "stage_6": "Reserve Optimization",
}

def _emit(callback: Optional[Callable], event_type: str, stage: Optional[str] = None, extra: Optional[dict] = None):
    """Emit a pipeline event. callback is called with a dict; no-ops if None."""
    if callback is None:
        return
    event = {
        "type": event_type,
        "stage": stage,
        "label": STAGE_LABELS.get(stage, stage) if stage else None,
        "ts": datetime.now(timezone.utc).isoformat(),
        "data": extra or {},
    }
    try:
        callback(event)
    except Exception:
        pass  # never let event emission crash the pipeline
logger = logging.getLogger(__name__)

ORCHESTRATOR_DIR = pathlib.Path(__file__).parent
ROOT_DIR = ORCHESTRATOR_DIR.parent
RUN_LOG_PATH = ORCHESTRATOR_DIR / "pipeline_runs.json"
SUPPLIERS_PATH = ROOT_DIR / "fixtures" / "suppliers.json"

def write_run_log(log_data: dict):
    runs = []
    if RUN_LOG_PATH.exists():
        try:
            with open(RUN_LOG_PATH, "r", encoding="utf-8") as f:
                runs = json.load(f)
        except json.JSONDecodeError:
            pass
    runs.insert(0, log_data)
    # Keep last 50 runs
    with open(RUN_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(runs[:50], f, indent=2)

def save_to_supabase(table: str, data: list[dict]):
    if not data:
        return
    try:
        supabase.table(table).insert(data).execute()
        logger.info(f"  Saved {len(data)} rows to {table}")
    except Exception as e:
        logger.error(f"  Failed to save to {table}: {e}")
        raise

def run_pipeline(event_callback: Optional[Callable] = None):
    start_time_total = time.time()
    started_at = datetime.now(timezone.utc).isoformat()
    run_id = str(uuid.uuid4())
    
    stage_timings = {}
    
    logger.info("="*60)
    logger.info(f"STARTING FULL PIPELINE RUN: {run_id}")
    logger.info("="*60)
    
    _emit(event_callback, "pipeline_start", extra={"run_id": run_id})

    # ------------------------------------------------------------------
    # STAGE 1: Data Collection
    # ------------------------------------------------------------------
    t0 = time.time()
    raw_signals = []
    eia_snapshot = {}
    _emit(event_callback, "stage_start", "stage_1")
    try:
        logger.info("[Stage 1] Ingesting OFAC signals...")
        ofac_signals, _ = fetch_ofac_signals()
        raw_signals.extend(ofac_signals)

        for corridor in ["hormuz", "red_sea"]:
            logger.info(f"[Stage 1] Ingesting RSS signals for {corridor}...")
            rss = fetch_rss_signals(corridor)
            raw_signals.extend(rss)

        logger.info("[Stage 1] Ingesting EIA crude oil price data...")
        eia_signals, eia_snapshot = fetch_eia_signals()
        raw_signals.extend(eia_signals)
        logger.info(
            f"[Stage 1] EIA: Brent $%s, WTI $%s, source=%s",
            eia_snapshot.get('brent_usd'), eia_snapshot.get('wti_usd'),
            eia_snapshot.get('data_source')
        )

        stage_timings["stage_1"] = time.time() - t0
        logger.info(f"[Stage 1] Collected {len(raw_signals)} raw signals. ({stage_timings['stage_1']:.2f}s)")
        save_to_supabase("raw_signals", raw_signals)
        _emit(event_callback, "stage_done", "stage_1", {
            "signals_collected": len(raw_signals),
            "eia_brent": eia_snapshot.get('brent_usd'),
            "eia_source": eia_snapshot.get('data_source'),
            "elapsed": round(stage_timings["stage_1"], 2)
        })
    except Exception as e:
        logger.error(f"[Stage 1] Failed: {e}")
        stage_timings["stage_1"] = time.time() - t0
        _emit(event_callback, "stage_error", "stage_1", {"error": str(e)})
        
    # ------------------------------------------------------------------
    # STAGE 2: Normalization
    # ------------------------------------------------------------------
    t0 = time.time()
    processed_signals = []
    _emit(event_callback, "stage_start", "stage_2")
    try:
        if raw_signals:
            logger.info("[Stage 2] Normalizing signals...")
            processed_signals = normalize_signals(raw_signals)
            stage_timings["stage_2"] = time.time() - t0
            logger.info(f"[Stage 2] Generated {len(processed_signals)} processed signals. ({stage_timings['stage_2']:.2f}s)")
            save_to_supabase("processed_signals", processed_signals)
            _emit(event_callback, "stage_done", "stage_2", {"processed": len(processed_signals), "elapsed": round(stage_timings["stage_2"], 2)})
        else:
            logger.warning("[Stage 2] Skipped (no raw signals)")
            stage_timings["stage_2"] = time.time() - t0
            _emit(event_callback, "stage_done", "stage_2", {"processed": 0, "skipped": True})
    except Exception as e:
        logger.error(f"[Stage 2] Failed: {e}")
        stage_timings["stage_2"] = time.time() - t0
        _emit(event_callback, "stage_error", "stage_2", {"error": str(e)})
        
    # ------------------------------------------------------------------
    # STAGE 3: Risk Intelligence
    # ------------------------------------------------------------------
    t0 = time.time()
    risk_scores = []
    _emit(event_callback, "stage_start", "stage_3")
    try:
        if processed_signals:
            logger.info("[Stage 3] Computing risk scores...")
            by_corridor = {}
            for s in processed_signals:
                c = s["corridor"]
                by_corridor.setdefault(c, []).append(s)
                
            for c, sigs in by_corridor.items():
                logger.info(f"  -> Scoring corridor: {c}")
                score = compute_risk_score(sigs, use_llm=True)
                risk_scores.append(score)
                time.sleep(3)
                
            stage_timings["stage_3"] = time.time() - t0
            logger.info(f"[Stage 3] Generated {len(risk_scores)} risk scores. ({stage_timings['stage_3']:.2f}s)")
            save_to_supabase("risk_scores", risk_scores)
            _emit(event_callback, "stage_done", "stage_3", {"corridors_scored": len(risk_scores), "elapsed": round(stage_timings["stage_3"], 2)})
        else:
            logger.warning("[Stage 3] Skipped (no processed signals)")
            stage_timings["stage_3"] = time.time() - t0
            _emit(event_callback, "stage_done", "stage_3", {"corridors_scored": 0, "skipped": True})
    except Exception as e:
        logger.error(f"[Stage 3] Failed: {e}")
        stage_timings["stage_3"] = time.time() - t0
        _emit(event_callback, "stage_error", "stage_3", {"error": str(e)})

    # ------------------------------------------------------------------
    # STAGE 4: Scenario Modeling
    # ------------------------------------------------------------------
    t0 = time.time()
    scenarios = []
    _emit(event_callback, "stage_start", "stage_4")
    try:
        logger.info("[Stage 4] Running scenario models...")
        scenario_map = {
            "hormuz_partial_closure": "hormuz",
            "red_sea_suspension": "red_sea",
            "opec_emergency_cut": "other"
        }
        risk_map = {rs["corridor"]: rs["risk_score"] for rs in risk_scores}
        
        for stype, target_corridor in scenario_map.items():
            if target_corridor in risk_map:
                severity = risk_map[target_corridor]
            else:
                severity = max(risk_map.values()) if risk_map else 0.5
            severity = max(0.1, min(1.0, severity))
            logger.info(f"  -> Scenario {stype} @ severity={severity:.2f}")
            scen = run_scenario(stype, severity, target_corridor)
            scenarios.append(scen)
            
        stage_timings["stage_4"] = time.time() - t0
        logger.info(f"[Stage 4] Generated {len(scenarios)} scenarios. ({stage_timings['stage_4']:.2f}s)")
        save_to_supabase("scenarios", scenarios)
        _emit(event_callback, "stage_done", "stage_4", {"scenarios_run": len(scenarios), "elapsed": round(stage_timings["stage_4"], 2)})
    except Exception as e:
        logger.error(f"[Stage 4] Failed: {e}")
        stage_timings["stage_4"] = time.time() - t0
        _emit(event_callback, "stage_error", "stage_4", {"error": str(e)})
        
    # ------------------------------------------------------------------
    # Find Highest Severity Scenario for Stages 5 & 6
    # ------------------------------------------------------------------
    highest_scenario = None
    if scenarios:
        highest_scenario = max(scenarios, key=lambda s: s["severity"])
        logger.info(f"Selected highest severity scenario for action: {highest_scenario['scenario_type']} (sev={highest_scenario['severity']:.2f})")
        
    # ------------------------------------------------------------------
    # STAGE 5: Procurement Orchestrator
    # ------------------------------------------------------------------
    t0 = time.time()
    recs = []
    _emit(event_callback, "stage_start", "stage_5")
    try:
        if highest_scenario:
            logger.info("[Stage 5] Ranking procurement suppliers...")
            with open(SUPPLIERS_PATH, "r", encoding="utf-8") as f:
                suppliers_data = json.load(f)
            recs = rank_suppliers(highest_scenario, suppliers_data)
            stage_timings["stage_5"] = time.time() - t0
            logger.info(f"[Stage 5] Generated {len(recs)} procurement recs. ({stage_timings['stage_5']:.2f}s)")
            save_to_supabase("procurement_recs", recs)
            _emit(event_callback, "stage_done", "stage_5", {"recs_generated": len(recs), "elapsed": round(stage_timings["stage_5"], 2)})
        else:
            logger.warning("[Stage 5] Skipped (no scenarios)")
            stage_timings["stage_5"] = time.time() - t0
            _emit(event_callback, "stage_done", "stage_5", {"recs_generated": 0, "skipped": True})
    except Exception as e:
        logger.error(f"[Stage 5] Failed: {e}")
        stage_timings["stage_5"] = time.time() - t0
        _emit(event_callback, "stage_error", "stage_5", {"error": str(e)})

    # ------------------------------------------------------------------
    # STAGE 6: Reserve Optimizer
    # ------------------------------------------------------------------
    t0 = time.time()
    reserve_plan = None
    _emit(event_callback, "stage_start", "stage_6")
    try:
        if highest_scenario:
            logger.info("[Stage 6] Optimizing strategic reserves...")
            reserve_plan = optimize_reserves(highest_scenario)
            stage_timings["stage_6"] = time.time() - t0
            logger.info(f"[Stage 6] Generated reserve plan. ({stage_timings['stage_6']:.2f}s)")
            save_to_supabase("reserve_plans", [reserve_plan])
            _emit(event_callback, "stage_done", "stage_6", {"days_cover": reserve_plan.get("days_of_cover_remaining"), "elapsed": round(stage_timings["stage_6"], 2)})
        else:
            logger.warning("[Stage 6] Skipped (no scenarios)")
            stage_timings["stage_6"] = time.time() - t0
            _emit(event_callback, "stage_done", "stage_6", {"skipped": True})
    except Exception as e:
        logger.error(f"[Stage 6] Failed: {e}")
        stage_timings["stage_6"] = time.time() - t0
        _emit(event_callback, "stage_error", "stage_6", {"error": str(e)})

    total_latency = time.time() - start_time_total
    
    # Generate run log
    log_data = {
        "id": run_id,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "stage_timings": stage_timings,
        "total_latency_seconds": round(total_latency, 3),
        "status": "success",
        "error_detail": "",
        "eia_snapshot": eia_snapshot,
        "metrics": {
            "signals_processed": len(raw_signals),
            "corridors_scored": len(risk_scores),
            "scenarios_run": len(scenarios),
            "recommendations_generated": len(recs)
        }
    }
    write_run_log(log_data)
    _emit(event_callback, "pipeline_done", extra={"run_id": run_id, "total_latency_seconds": round(total_latency, 3)})

    logger.info("="*60)
    logger.info(f"PIPELINE COMPLETE in {total_latency:.2f}s")
    for st, t in stage_timings.items():
        logger.info(f"  {st}: {t:.2f}s")
    logger.info("="*60)
    
    return log_data

if __name__ == "__main__":
    run_pipeline()
