import requests
import time
from datetime import datetime, timezone

def test_pipeline():
    print("="*60)
    print("Testing End-to-End Pipeline & API")
    print("="*60)
    
    # We assume the uvicorn server is running on http://localhost:8001
    base_url = "http://localhost:8001"
    
    # 1. Trigger the pipeline via the new API endpoint
    print("1. Triggering full pipeline via /api/pipeline/run...")
    start = time.time()
    try:
        res = requests.post(f"{base_url}/api/pipeline/run", timeout=120)
        res.raise_for_status()
        log_data = res.json()
        latency = log_data["total_latency_seconds"]
        print(f"   [SUCCESS] Pipeline finished in {latency}s")
    except Exception as e:
        print(f"   [ERROR] Failed to run pipeline: {e}")
        return
        
    print(f"\n   [Headline Latency]: {latency} seconds total end-to-end.")
    print("   Stage Timings:")
    for stage, t in log_data["stage_timings"].items():
        print(f"      {stage}: {t:.2f}s")
        
    # 2. Check risk scores
    print("\n2. Checking /api/risk-scores...")
    res = requests.get(f"{base_url}/api/risk-scores")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    scores = res.json()
    print(f"   [SUCCESS] Found {len(scores)} recent risk scores.")
    
    # 3. Check scenarios
    print("\n3. Checking /api/scenarios...")
    res = requests.get(f"{base_url}/api/scenarios")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    scenarios = res.json()
    print(f"   [SUCCESS] Found {len(scenarios)} recent scenarios.")
    if not scenarios:
        print("   [ERROR] No scenarios generated.")
        return
        
    # 4. Check procurement recs
    print(f"\n4. Checking /api/procurement-recs...")
    recs = []
    working_sid = None
    for s in scenarios:
        res = requests.get(f"{base_url}/api/procurement-recs", params={"scenario_id": s["id"]})
        if res.status_code == 200:
            recs = res.json()
            working_sid = s["id"]
            break
            
    assert len(recs) > 0, "Expected to find procurement recs for at least one scenario, got none"
    print(f"   [SUCCESS] Found {len(recs)} procurement recommendations for scenario {working_sid}.")
    
    # 5. Check reserve plans
    print(f"\n5. Checking /api/reserve-plan?scenario_id={working_sid}...")
    res = requests.get(f"{base_url}/api/reserve-plan", params={"scenario_id": working_sid})
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    plan = res.json()
    print(f"   [SUCCESS] Found reserve plan (days_of_cover_remaining={plan.get('days_of_cover_remaining')})")
    
    # 6. Check pipeline status
    print("\n6. Checking /api/pipeline-status...")
    res = requests.get(f"{base_url}/api/pipeline-status")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    status = res.json()
    print(f"   [SUCCESS] Status endpoint working. Last run completed at: {status['completed_at']}")
    
    print("\n="*60)
    print("ALL TESTS PASSED.")
    print(f"End-to-End Latency: {latency:.2f}s")
    print("="*60)

if __name__ == "__main__":
    test_pipeline()
