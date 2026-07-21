-- =============================================================================
-- AI-Driven Energy Supply Chain Resilience — Supabase Schema
-- Run this entire file in your Supabase SQL editor (Dashboard → SQL Editor → New query)
-- RLS is intentionally disabled for hackathon (service_role key used service-to-service)
-- =============================================================================

-- -------------------------------------------------------
-- Stage 1 output: raw ingested signals from all sources
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_signals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source          TEXT NOT NULL CHECK (source IN ('rss','ais','ofac','eia','price_feed','mock')),
    timestamp       TIMESTAMPTZ NOT NULL,
    corridor        TEXT NOT NULL CHECK (corridor IN ('hormuz','red_sea','suez','other')),
    raw_payload     JSONB NOT NULL DEFAULT '{}',
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------
-- Stage 2 output: normalized/validated processed signals
-- One row per RSS article (signal_type='news'); ONE aggregated row per corridor for OFAC (signal_type='sanctions').
-- contributing_signals stores the raw_signal IDs that fed this processed row.
-- -------------------------------------------------------
DROP TABLE IF EXISTS processed_signals CASCADE;
CREATE TABLE processed_signals (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    corridor                TEXT NOT NULL CHECK (corridor IN ('hormuz','red_sea','suez','other')),
    signal_type             TEXT NOT NULL CHECK (signal_type IN ('news','shipping','sanctions','price')),
    severity_hint           DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    text_summary            TEXT NOT NULL DEFAULT '',
    contributing_signals    TEXT[] NOT NULL DEFAULT '{}',
    source                  TEXT NOT NULL DEFAULT 'real',
    generated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------
-- Stage 3 output: risk score per corridor/supplier
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS risk_scores (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    corridor                TEXT NOT NULL CHECK (corridor IN ('hormuz','red_sea','suez','other')),
    supplier                TEXT,
    risk_score              DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    confidence              DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    explanation             TEXT NOT NULL DEFAULT '',
    contributing_signals    TEXT[] NOT NULL DEFAULT '{}',
    -- detail: transparent breakdown (acute_score, sanctions_floor, signals_present/
    -- missing, renormalised leading weights, confidence band). See risk_intelligence.py.
    detail                  JSONB NOT NULL DEFAULT '{}',
    source                  TEXT NOT NULL CHECK (source IN ('real','mock')),
    generated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------
-- Stage 4 output: disruption scenario simulations
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS scenarios (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_type                   TEXT NOT NULL,
    severity                        DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    supply_gap_pct                  DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    price_impact_pct                DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    refinery_utilization_impact_pct DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    spr_days_remaining_estimate     DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    assumptions                     TEXT[] NOT NULL DEFAULT '{}',
    -- detail: low/expected/high uncertainty bands per metric + UI assumptions block.
    -- See scenario_modeling.py.
    detail                          JSONB NOT NULL DEFAULT '{}',
    generated_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------
-- Stage 5 output: procurement recommendations
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS procurement_recs (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id                 UUID REFERENCES scenarios(id),
    rank                        INTEGER NOT NULL DEFAULT 1,
    supplier                    TEXT NOT NULL DEFAULT '',
    route                       TEXT NOT NULL DEFAULT '',
    spot_price_est              DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    transit_time_days           DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    refinery_compatibility_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    overall_score               DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    rationale                   TEXT NOT NULL DEFAULT '',
    source                      TEXT NOT NULL CHECK (source IN ('real','mock')),
    generated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------
-- Stage 6 output: strategic reserve drawdown plans
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS reserve_plans (
    id                                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id                         UUID REFERENCES scenarios(id),
    drawdown_schedule                   JSONB NOT NULL DEFAULT '[]',
    days_of_cover_remaining             DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    replenishment_window_estimate_days  DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    policy_recommendation               TEXT NOT NULL DEFAULT '',
    generated_at                        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------
-- Stage 7 output: compiled human-readable reports
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS reports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id     UUID REFERENCES scenarios(id),
    risk_score_id   UUID REFERENCES risk_scores(id),
    title           TEXT NOT NULL DEFAULT '',
    body_markdown   TEXT NOT NULL DEFAULT '',
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- Indexes for common query patterns
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_raw_signals_corridor     ON raw_signals(corridor);
CREATE INDEX IF NOT EXISTS idx_raw_signals_timestamp    ON raw_signals(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_processed_signals_corridor    ON processed_signals(corridor);
CREATE INDEX IF NOT EXISTS idx_processed_signals_generated   ON processed_signals(generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_risk_scores_corridor     ON risk_scores(corridor);
CREATE INDEX IF NOT EXISTS idx_risk_scores_generated_at ON risk_scores(generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_scenarios_type           ON scenarios(scenario_type);
CREATE INDEX IF NOT EXISTS idx_procurement_scenario     ON procurement_recs(scenario_id);
CREATE INDEX IF NOT EXISTS idx_reserve_scenario         ON reserve_plans(scenario_id);
CREATE INDEX IF NOT EXISTS idx_reports_scenario         ON reports(scenario_id);

-- =============================================================================
-- MIGRATIONS — idempotent ALTERs for EXISTING deployments.
-- The CREATE TABLE statements above use IF NOT EXISTS, so on an already-provisioned
-- database the new `detail` columns are NOT added by the CREATE. Run these ALTERs
-- (safe to re-run) to bring an existing risk_scores/scenarios table up to date.
--
--   detail on risk_scores  = { acute_score, sanctions_floor, score_driver,
--                              signals_present, signals_missing, leading_weights,
--                              type_severity, confidence_band }
--   detail on scenarios    = { <metric>_band:{low,expected,high} per metric,
--                              confidence, assumptions_block }
-- =============================================================================
ALTER TABLE risk_scores ADD COLUMN IF NOT EXISTS detail JSONB NOT NULL DEFAULT '{}';
ALTER TABLE scenarios   ADD COLUMN IF NOT EXISTS detail JSONB NOT NULL DEFAULT '{}';

-- -------------------------------------------------------
-- Pipeline Run Logs
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    stage_timings JSONB,
    total_latency_seconds FLOAT,
    status TEXT,
    error_detail TEXT
);
