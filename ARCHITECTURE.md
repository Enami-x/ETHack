# ARCHITECTURE.md
## AI-Driven Energy Supply Chain Resilience — Project Spec

**Purpose of this file:** This is the persistent source of truth for the project. Paste this into every new Claude Code session (or keep it in repo root and tell Claude Code to read it first). Every agent must conform to the schemas below — do not let the model redesign them mid-build.

---

## 1. Build Philosophy

1. **Vertical slice first.** A hardcoded/mocked signal must flow through all 8 stages and reach the dashboard before any single stage gets "smart." This is stage 0 of the build.
2. **Each agent is a pure function** with a fixed JSON input and JSON output. It does not call other agents directly — it reads from and writes to shared state (see §4).
3. **Mock vs Real is explicit per stage** (see §3). Never silently fabricate data that looks real without labeling it `"source": "mock"` in the output.
4. **Build priority follows judging weight**, not pipeline order (see §5).

---

## 2. Tech Stack (locked — do not relitigate per session)

| Layer | Choice | Notes |
|---|---|---|
| Backend | FastAPI (Python) | one service per agent, or modular monolith with clear module boundaries |
| Shared state | Supabase (Postgres + REST/Realtime) | hosted, no local DB setup, gives you Realtime subscriptions for free if the dashboard wants live updates |
| Frontend | React + a mapping lib (Mapbox GL / deck.gl free tier) | dashboard + geospatial view |
| LLM calls | Claude API (Sonnet) | risk explanations, procurement rationale, news summarization |
| Scheduling | simple cron/interval loop, not Airflow | keep it debuggable |
| Orchestration | shared Supabase tables, NOT LangGraph/heavy frameworks | unless team already knows the framework cold |

---

## 3. Data Sources — Mock vs Real

| Source | Status | Notes |
|---|---|---|
| GDELT news feed | REAL (free API) | good, high-signal, easy win |
| AIS vessel tracking | REAL (MarineTraffic free tier, rate-limited) | fallback to mock if rate-limited during demo |
| OFAC sanctions registry | REAL (static CSV, public) | trivial to ingest, looks credible to judges |
| EIA commodity/crude data | REAL (free API) | |
| Brent/spot pricing | REAL (Alpha Vantage free tier or scraped) | |
| Refinery-level operational data | MOCK | not publicly available at this granularity — label clearly |
| Tanker charter rates / port congestion | MOCK | plausible synthetic values, documented assumptions |
| GDP trajectory modeling | MOCK/SIMPLIFIED | use a documented parametric formula, not ML — judges reward explicit testable assumptions over fake precision |

**Rule:** anything mocked must be flagged in the deck as "would integrate [X] in production" — do not present mocked precision as real.

---

## 4. Shared State Schema

All stages read/write through shared Supabase tables (accessed via `supabase-py` from each FastAPI agent). Suggested tables:

```
raw_signals        -- stage 1 output
risk_scores        -- stage 3 output
scenarios          -- stage 4 output
procurement_recs   -- stage 5 output
reserve_plans      -- stage 6 output
reports            -- stage 7 output
```

**Notes:**
- Use one Supabase project for the whole hackathon build — don't spin up per-agent projects.
- Row Level Security (RLS) can stay **disabled** for the hackathon (internal service-to-service calls via the `service_role` key) — don't burn time on auth policies unless a judge-facing feature needs it.
- The dashboard (Stage 8) can use Supabase Realtime subscriptions on `risk_scores` / `scenarios` to get "live updates" essentially for free, which directly supports the "continuous, not weekly" and "real-time updates" claims in your feature spec.
- Store the Supabase URL and `service_role` key in `.env` — never commit them. Add `.env` to `.gitignore` before your first commit.

---

## 5. Pipeline Stages — Build Order, Priority, and Schemas

### Priority tier (build in this order):
1. **Vertical slice (mocked end-to-end)**
2. **Risk Intelligence Agent** — Innovation + Business Impact weight (50% combined)
3. **Procurement Orchestrator** — same weight tier, "executable within hours" is a named eval criterion
4. **Scenario Modeller** — can be rule-based/parametric, not ML
5. **Dashboard + Geospatial view** — UX weight (15%), highest visual payoff per hour spent
6. **Reserve Optimizer** — simplify to a drawdown formula, lowest priority to make "smart"
7. **Reporting agent** — thin wrapper, mostly templating

---

### Stage 1 — Data Collection
**Responsibility:** ingest raw signals from news, AIS, sanctions, price feeds.

**Output schema (`raw_signals` row):**
```json
{
  "id": "uuid",
  "source": "gdelt | ais | ofac | eia | price_feed | mock",
  "timestamp": "ISO8601",
  "corridor": "hormuz | red_sea | suez | other",
  "raw_payload": { "...source-specific fields..." },
  "ingested_at": "ISO8601"
}
```

### Stage 2 — Data Processing
**Responsibility:** normalize/validate raw_signals into a common shape.

**Output schema:**
```json
{
  "id": "uuid",
  "corridor": "hormuz | red_sea | suez | other",
  "signal_type": "news | shipping | sanctions | price",
  "severity_hint": 0.0,
  "text_summary": "string",
  "timestamp": "ISO8601"
}
```

### Stage 3 — Risk Intelligence Agent
**Responsibility:** produce a live disruption probability score per corridor/supplier, with explanation.

**Input:** processed signals (stage 2 output, filtered by corridor/supplier)

**Output schema (`risk_scores` row):**
```json
{
  "id": "uuid",
  "corridor": "hormuz",
  "supplier": "string | null",
  "risk_score": 0.0,
  "confidence": 0.0,
  "explanation": "LLM-generated natural language string",
  "contributing_signals": ["signal_id_1", "signal_id_2"],
  "source": "real | mock",
  "generated_at": "ISO8601"
}
```

**Build note:** start with a transparent weighted formula (not a black-box model) — "transparent scoring formulas" is explicitly named in your own spec and in judging criteria under explainability.

**Validation note (post-hoc):** SIGNAL_TYPE_WEIGHTS (sanctions=0.40, news=0.30, shipping=0.20, price=0.10) were empirically tested against 18 historical disruption events (2015–2026) via linear regression against actual realized price impact. LOOCV R² = -0.06, indicating the sample (18 events / 4 correlated features) is too thin to trust an empirical override — see /research/calibrate_stage3.py. The regression over-weighted price (a lagging indicator that trivially correlates with the outcome being predicted), confirming the original expert-judgment rank order (sanctions > news > shipping > price, leading indicators first) is more defensible for a *predictive* risk score than a fit that rewards circularity. Current weights were kept unchanged. Full reasoning and paste-ready summary in /research/calibrate_stage3.py output.

### Stage 4 — Scenario Modeling Agent
**Responsibility:** simulate named disruption events, compute cascading impacts.

**Input:** a scenario trigger (`hormuz_partial_closure`, `opec_emergency_cut`, `red_sea_suspension`) + current risk_scores + severity slider value

**Output schema (`scenarios` row):**
```json
{
  "id": "uuid",
  "scenario_type": "hormuz_partial_closure",
  "severity": 0.0,
  "supply_gap_pct": 0.0,
  "price_impact_pct": 0.0,
  "refinery_utilization_impact_pct": 0.0,
  "spr_days_remaining_estimate": 0.0,
  "assumptions": ["explicit assumption strings — REQUIRED, judges score on this"],
  "generated_at": "ISO8601"
}
```

**Build note:** keep this parametric/formula-driven for the hackathon. "Assumptions must be explicit and testable" is a direct line from the judging criteria — write the formula into the code comments and surface it in the UI.

**Validation note (post-hoc):** the three elasticity multipliers (Hormuz 1.8×, OPEC 2.2×, Red Sea 1.3×) were tested against 18 historical events grouped by scenario type — see /research/calibrate_stage4.py. All three groups returned R² well below the 0.30 trust threshold (largest group, Hormuz-mapped "Middle East Total" events, N=12, R²=-0.017), because the grouping conflated supply-cut events (price falls) with closure/attack events (price rises) under one label. Current multipliers were kept, cited to their original calibration anchors (documented per-scenario in the assumptions list). Documented as a legitimate limitation: n=18 events across 3 scenario types is insufficient for empirical elasticity fitting; a production system would need a larger, cleanly-labeled event corpus.

### Stage 5 — Procurement Agent
**Responsibility:** rank alternative crude sources/routes given a scenario.

**Input:** active scenario + supplier database (mock fixture) + current risk_scores

**Output schema (`procurement_recs` row):**
```json
{
  "id": "uuid",
  "scenario_id": "uuid",
  "rank": 1,
  "supplier": "string",
  "route": "string",
  "spot_price_est": 0.0,
  "transit_time_days": 0.0,
  "refinery_compatibility_score": 0.0,
  "overall_score": 0.0,
  "rationale": "LLM-generated string",
  "source": "real | mock",
  "generated_at": "ISO8601"
}
```

### Stage 6 — Reserve Optimization Agent
**Responsibility:** model SPR drawdown against the active scenario's supply gap.

**Output schema (`reserve_plans` row):**
```json
{
  "id": "uuid",
  "scenario_id": "uuid",
  "drawdown_schedule": [{"day": 1, "draw_pct": 0.0}],
  "days_of_cover_remaining": 0.0,
  "replenishment_window_estimate_days": 0.0,
  "policy_recommendation": "string",
  "generated_at": "ISO8601"
}
```

### Stage 7 — Reporting Agent
**Responsibility:** compile stages 3-6 into a human-readable report.

**Output:** markdown or PDF export, templated from the above records — no new logic, just formatting.

### Stage 8 — Dashboard
**Responsibility:** present live risk map, scenario explorer, recommendation tables, reserve analytics.

**Consumes:** all shared state tables either via API endpoints (`GET /risk_scores`, `GET /scenarios`, etc.) or directly via the Supabase client with Realtime subscriptions for live-updating widgets (risk heatmap, scenario explorer).

---

## 6. Definition of Done for the Hackathon Demo

- [ ] Vertical slice: 1 mock signal → risk score → scenario → 1 procurement rec → 1 reserve plan → visible on dashboard
- [ ] Risk Intelligence Agent running on ≥2 real data sources with visible explanation text
- [ ] At least 1 named scenario (e.g. Hormuz partial closure) fully simulated with explicit assumptions shown in UI
- [ ] Procurement ranking with ≥3 ranked alternatives and rationale text
- [ ] Map view showing at least Hormuz + Red Sea corridors with risk-colored status
- [ ] End-to-end signal-to-recommendation latency measured and stated in the deck (this is a named eval metric — don't skip measuring it)

---

## 7. Session Prompting Pattern (how to use this file with Claude Code)

For each stage, prompt roughly like:

> "Read ARCHITECTURE.md. Build Stage 3 (Risk Intelligence Agent) only. Input: rows from the `processed_signals` Supabase table matching the schema in §5 Stage 2. Output: rows written to the `risk_scores` Supabase table matching the schema in §5 Stage 3 exactly. Use a transparent weighted formula, not an ML model. Write a CLI test harness that runs against the fixture file at `fixtures/processed_signals_sample.json` (not live Supabase) and prints the resulting risk_scores before any DB write. Do not modify any other stage or file outside this agent's module."

Keep every stage prompt this scoped. Only wire stages together once each one passes its own fixture test independently.