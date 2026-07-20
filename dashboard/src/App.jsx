/**
 * App.jsx — Stage 8 Dashboard shell
 *
 * Tabs:
 *   1. Dashboard — MetricStrip, CorridorMap, ScenarioPanel, DrawdownChart,
 *                  ProcurementTable, RiskExplanationPanel
 *   2. Agent View — n8n-style live workflow visualisation
 */
import { useState, useEffect, useRef } from 'react';
import './index.css';

import MetricStrip          from './components/MetricStrip';
import CorridorMap          from './components/CorridorMap';
import ScenarioPanel        from './components/ScenarioPanel';
import DrawdownChart        from './components/DrawdownChart';
import ProcurementTable     from './components/ProcurementTable';
import RiskExplanationPanel from './components/RiskExplanationPanel';
import AgentView            from './components/AgentView';
import CrudeOilPanel        from './components/CrudeOilPanel';
import RoutingAdvisorPanel  from './components/RoutingAdvisorPanel';

import { fetchRiskScores, triggerPipeline } from './api';

export default function App() {
  // ── Tab state ──────────────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState('dashboard'); // 'dashboard' | 'routes' | 'agents'

  // ── Dashboard shared state ─────────────────────────────────────────────
  const [activeScenario,    setActiveScenario]    = useState(null);
  const [selectedCorridor,  setSelectedCorridor]  = useState(null);
  const [riskScores,        setRiskScores]         = useState([]);

  // ── Pipeline run state (shared with header) ────────────────────────────
  const [running,           setRunning]            = useState(false);
  const [elapsed,           setElapsed]            = useState(0);
  const [pipelineResult,    setPipelineResult]     = useState(null);
  const [pipelineError,     setPipelineError]      = useState(null);
  const intervalRef = useRef(null);

  // ── Keep riskScores in sync ───────────────────────────────────────────
  useEffect(() => {
    async function load() {
      try {
        const data = await fetchRiskScores();
        setRiskScores(data);
      } catch { /* graceful */ }
    }
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, []);

  // ── Run pipeline (from header button, for Dashboard tab) ───────────────
  async function handleRunPipeline() {
    setRunning(true);
    setElapsed(0);
    setPipelineResult(null);
    setPipelineError(null);

    intervalRef.current = setInterval(() => setElapsed(e => e + 1), 1000);

    try {
      const result = await triggerPipeline();
      setPipelineResult(result);
    } catch (err) {
      const msg = err?.response?.data?.detail ?? err?.message ?? 'Unknown error';
      setPipelineError(`Pipeline failed: ${msg}`);
    } finally {
      clearInterval(intervalRef.current);
      setRunning(false);
    }
  }

  return (
    <div className="app-shell">
      {/* ── Header ──────────────────────────────────────────────────── */}
      <header className="app-header">
        <div>
          <h1>⚡ Energy Supply Chain Resilience</h1>
          <div className="subtitle">AI-driven geopolitical risk · live pipeline</div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {pipelineResult && activeTab === 'dashboard' && (
            <span style={{ fontSize: 11, color: 'var(--risk-low)' }}>
              ✓ Completed in {pipelineResult.total_latency_seconds?.toFixed(1) ?? '—'}s
            </span>
          )}
          {pipelineError && activeTab === 'dashboard' && (
            <span style={{ fontSize: 11, color: 'var(--amber)' }}>{pipelineError}</span>
          )}

          {/* Show run button only on Dashboard tab */}
          {activeTab === 'dashboard' && (
            <button
              className="btn btn-primary"
              onClick={handleRunPipeline}
              disabled={running}
            >
              {running ? (
                <>
                  <span className="spinner" />
                  Running… {elapsed}s
                </>
              ) : (
                '▶ Run pipeline'
              )}
            </button>
          )}
        </div>
      </header>

      {/* ── Tab bar ──────────────────────────────────────────────────── */}
      <div className="tab-bar">
        <button
          className={`tab-btn ${activeTab === 'dashboard' ? 'active' : ''}`}
          onClick={() => setActiveTab('dashboard')}
          id="tab-dashboard"
        >
          <span className="tab-icon">📈</span>
          Dashboard
        </button>
        <button
          className={`tab-btn ${activeTab === 'routes' ? 'active' : ''}`}
          onClick={() => setActiveTab('routes')}
          id="tab-routes"
        >
          <span className="tab-icon">🚢</span>
          Route Advisor
        </button>
        <button
          className={`tab-btn ${activeTab === 'agents' ? 'active' : ''}`}
          onClick={() => setActiveTab('agents')}
          id="tab-agents"
        >
          <span className="tab-icon">🤖</span>
          Agent View
        </button>
      </div>

      {/* ── Tab: Dashboard ──────────────────────────────────────────── */}
      {activeTab === 'dashboard' && (
        <div className="main-grid">
          <MetricStrip />

          {/* Live crude oil prices from EIA */}
          <CrudeOilPanel />

          <div className="row-two">
            <CorridorMap onSelectCorridor={setSelectedCorridor} />

            <div className="right-stack">
              <ScenarioPanel onScenarioChange={setActiveScenario} />
              <DrawdownChart scenarioId={activeScenario?.id} />
            </div>
          </div>

          <ProcurementTable
            scenarioId={activeScenario?.id}
            activeScenario={activeScenario}
          />

          <RiskExplanationPanel
            corridorId={selectedCorridor}
            riskScores={riskScores}
          />
        </div>
      )}

      {/* ── Tab: Route Advisor ──────────────────────────────────────── */}
      {activeTab === 'routes' && (
        <RoutingAdvisorPanel />
      )}

      {/* ── Tab: Agent View ─────────────────────────────────────────── */}
      {activeTab === 'agents' && (
        <AgentView
          externalRunning={running}
          externalResult={pipelineResult}
        />
      )}
    </div>
  );
}
