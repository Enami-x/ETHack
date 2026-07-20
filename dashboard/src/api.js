/**
 * api.js — thin client for the ETHack FastAPI backend.
 * Base URL is read from the env var VITE_API_BASE_URL.
 * Falls back to http://localhost:8000 so the dev server works out of the box.
 */
import axios from 'axios';

const BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

const api = axios.create({ baseURL: BASE, timeout: 15000 });

/** GET /api/risk-scores — latest score per corridor */
export async function fetchRiskScores() {
  const { data } = await api.get('/api/risk-scores');
  return data; // array of risk_score rows
}

/** GET /api/scenarios — latest scenario per type */
export async function fetchScenarios() {
  const { data } = await api.get('/api/scenarios');
  return data; // array of scenario rows
}

/** GET /api/procurement-recs?scenario_id=X */
export async function fetchProcurementRecs(scenarioId) {
  const { data } = await api.get('/api/procurement-recs', {
    params: { scenario_id: scenarioId },
  });
  return data; // array of procurement_recs rows
}

/** GET /api/reserve-plan?scenario_id=X */
export async function fetchReservePlan(scenarioId) {
  const { data } = await api.get('/api/reserve-plan', {
    params: { scenario_id: scenarioId },
  });
  return data; // single reserve_plan row
}

/** GET /api/pipeline-status — latest pipeline run log entry */
export async function fetchPipelineStatus() {
  const { data } = await api.get('/api/pipeline-status');
  return data;
}

/** POST /api/pipeline/run — trigger full pipeline (takes ~30 s) */
export async function triggerPipeline() {
  const { data } = await api.post('/api/pipeline/run', null, { timeout: 120000 });
  return data;
}

/** POST /api/pipeline/simulate — instant mock run (no external calls) */
export async function simulatePipeline() {
  const { data } = await api.post('/api/pipeline/simulate', null, { timeout: 30000 });
  return data;
}

/**
 * GET /api/crude-oil — live EIA crude oil snapshot
 * Returns Brent/WTI prices, 30-day series, inventory, refinery data
 */
export async function fetchCrudeOil() {
  const { data } = await api.get('/api/crude-oil');
  return data;
}

/** GET /api/route/ports — list of all available ports for the Route Advisor */
export async function fetchAvailablePorts() {
  const { data } = await api.get('/api/route/ports');
  return data; // array of { id, name, coords, region }
}

/** POST /api/route/assess — assess alternative shipping routes */
export async function assessRoute(origin, destination) {
  const { data } = await api.post('/api/route/assess', { origin, destination });
  return data;
}

/**
 * GET /api/pipeline/stream — SSE stream of live stage events.
 * Returns a native EventSource object. Caller is responsible for .close()
 */
export function createPipelineStream() {
  return new EventSource(`${BASE}/api/pipeline/stream`);
}
