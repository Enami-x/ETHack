# Energy Supply Chain Resilience API

An end-to-end Machine Learning pipeline and API designed to predict, model, and mitigate geopolitical disruptions to global crude oil supply chains. 

Built for real-time geopolitical intelligence, this system ingests raw OSINT data, computes active risk scores, models macro-economic supply scenarios, and dynamically recommends procurement pivots and strategic reserve drawdowns.

## System Architecture

The core orchestration pipeline is divided into 6 discrete stages:

1. **Stage 1: Data Ingestion (`agents/ingest_ofac.py` & `ingest_rss.py`)**
   - Fetches and caches the U.S. Treasury OFAC SDN list, utilizing a two-pass precision filter to isolate Iranian petroleum/shipping sanctions.
   - Parses marine and geopolitical RSS feeds (e.g., GCaptain, OilPrice, Al Jazeera) for early-warning indicators in key transit corridors (Hormuz, Red Sea).

2. **Stage 2: Signal Normalization (`agents/normalize_signals.py`)**
   - Transforms heterogeneous raw signals into a standardized schema for downstream processing.

3. **Stage 3: Risk Intelligence (`agents/risk_intelligence.py`)**
   - Uses a Large Language Model (Gemini) to evaluate the severity and confidence of the normalized signals, producing a consolidated `risk_score` (0.0 to 1.0) for each corridor.

4. **Stage 4: Scenario Modeling (`agents/scenario_modeling.py`)**
   - Dynamically models three primary disruption scenarios: `hormuz_partial_closure`, `red_sea_suspension`, and `opec_emergency_cut`.
   - Computes global supply gaps, estimated Brent crude price impacts, and refinery utilization drops based on the live `risk_score`.

5. **Stage 5: Procurement Orchestrator (`agents/procurement_orchestrator.py`)**
   - Evaluates a realistic matrix of alternative global crude suppliers (e.g., USA WTI, Guyana, Brazil, Nigeria).
   - Ranks the best pivot options based on transit time, refinery compatibility, and real-time spot price estimates to bypass the active disruption.

6. **Stage 6: Strategic Reserve Optimizer (`agents/reserve_optimizer.py`)**
   - Calculates a daily drawdown schedule for the Strategic Petroleum Reserve (SPR) based on the specific scenario's disruption window and the calculated supply gap.

## Project Structure

- `api/main.py`: The FastAPI application exposing the pipeline data.
- `agents/`: The individual ML/logic agents handling Stages 1-6.
- `orchestrator/`: Contains `run_full_pipeline.py` which sequences the stages end-to-end, and `test_full_pipeline.py` for integration testing.
- `research/`: Standalone scripts (`calibrate_stage3.py`, `calibrate_stage4.py`) used to empirically backtest pipeline elasticities against historical disruption datasets.
- `fixtures/`: Static JSON datasets used for modeling (e.g., alternative suppliers).
- `supabase_schema.sql`: The database schema definition for the 6 core tables + run logs.

## Setup & Installation

1. **Clone the repository and install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment Variables:**
   Create a `.env` file in the root directory and add your credentials:
   ```env
   SUPABASE_URL=https://your-project-id.supabase.co
   SUPABASE_SERVICE_KEY=your-service-role-key
   GEMINI_API_KEY=your-google-gemini-key
   ```

3. **Database Initialization:**
   Copy the contents of `supabase_schema.sql` and run it in your Supabase project's SQL Editor to create the required tables.

## Running the Project

### Start the API Server
Run the FastAPI backend using Uvicorn:
```bash
python -m uvicorn api.main:app --reload --port 8000
```
*The API documentation will be available at `http://localhost:8000/docs`.*

### Trigger the Pipeline
You can run the full end-to-end orchestration pipeline in two ways:

**Option 1: Directly via Python (Recommended for CLI testing)**
```bash
python orchestrator/run_full_pipeline.py
```

**Option 2: Via the API Endpoint**
Send a `POST` request to the trigger endpoint:
```bash
curl -X POST http://localhost:8000/api/pipeline/run
```

### Run the Integration Tests
To ensure the pipeline completes successfully and all API endpoints return valid, schema-compliant data, run the test suite:
```bash
python orchestrator/test_full_pipeline.py
```
This script will trigger the pipeline, wait for completion, and verify all downstream REST endpoints.

## API Endpoints

- `GET /` — Health check
- `POST /api/pipeline/run` — Triggers the orchestration pipeline synchronously.
- `GET /api/pipeline-status` — Retrieves latency metadata and timings from the latest run.
- `GET /api/risk-scores` — Returns the latest calculated risk scores per transit corridor.
- `GET /api/scenarios` — Returns the current macroeconomic impact models.
- `GET /api/procurement-recs?scenario_id={id}` — Returns ranked alternative supplier recommendations for a specific scenario.
- `GET /api/reserve-plan?scenario_id={id}` — Returns the calculated SPR drawdown plan.
