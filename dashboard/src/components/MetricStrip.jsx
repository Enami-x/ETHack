/**
 * MetricStrip.jsx
 * 4 metric cards at the top: Hormuz risk, Red Sea risk, SPR days remaining,
 * pipeline latency. Auto-refreshes every 30 s via polling.
 */
import { useState, useEffect, useCallback } from 'react';
import { fetchRiskScores, fetchScenarios, fetchReservePlan, fetchPipelineStatus } from '../api';

function riskClass(score) {
  if (score == null) return '';
  if (score < 0.4)  return 'low';
  if (score <= 0.7) return 'mid';
  return 'high';
}

function RiskBadge({ score }) {
  if (score == null) return <span className="metric-sub">—</span>;
  const cls = riskClass(score);
  const label = cls === 'low' ? 'LOW' : cls === 'mid' ? 'MED' : 'HIGH';
  return (
    <span className={`risk-badge ${cls}`} style={{ marginTop: 6, fontSize: 10 }}>
      <span className="risk-dot" />
      {label}
    </span>
  );
}

export default function MetricStrip() {
  const [hormuzScore, setHormuzScore] = useState(null);
  const [redSeaScore, setRedSeaScore] = useState(null);
  const [sprDays, setSprDays]         = useState(null);
  const [latency, setLatency]         = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);

  const load = useCallback(async () => {
    // ── Risk scores ──
    try {
      const scores = await fetchRiskScores();
      const hz = scores.find(r => r.corridor === 'hormuz');
      const rs = scores.find(r => r.corridor === 'red_sea');
      setHormuzScore(hz?.risk_score ?? null);
      setRedSeaScore(rs?.risk_score ?? null);
    } catch (_) { /* backend not up yet — keep null */ }

    // ── SPR days (highest-severity scenario's reserve plan) ──
    try {
      const scenarios = await fetchScenarios();
      if (scenarios.length) {
        const top = scenarios.reduce((best, s) =>
          (s.severity ?? 0) > (best.severity ?? 0) ? s : best, scenarios[0]);
        const plan = await fetchReservePlan(top.id);
        setSprDays(plan?.days_of_cover_remaining ?? null);
      }
    } catch (_) { /* keep null */ }

    // ── Pipeline latency ──
    try {
      const status = await fetchPipelineStatus();
      // status.status === 'no_runs_yet' when no pipeline has run yet
      setLatency(status?.total_latency_seconds ?? null);
    } catch (_) { /* keep null */ }

    setLastRefresh(new Date());
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 30_000);
    return () => clearInterval(timer);
  }, [load]);

  const fmt = v => v != null ? Number(v).toFixed(2) : '—';

  return (
    <div>
      <div className="metric-strip">
        {/* Hormuz risk */}
        <div className="metric-card">
          <div className="metric-label">Hormuz Risk</div>
          <div className="metric-value" style={{ color: hormuzScore != null ? `var(--risk-${riskClass(hormuzScore)})` : 'var(--text-3)' }}>
            {fmt(hormuzScore)}
          </div>
          <RiskBadge score={hormuzScore} />
        </div>

        {/* Red Sea risk */}
        <div className="metric-card">
          <div className="metric-label">Red Sea Risk</div>
          <div className="metric-value" style={{ color: redSeaScore != null ? `var(--risk-${riskClass(redSeaScore)})` : 'var(--text-3)' }}>
            {fmt(redSeaScore)}
          </div>
          <RiskBadge score={redSeaScore} />
        </div>

        {/* SPR days remaining */}
        <div className="metric-card">
          <div className="metric-label">SPR Cover (days)</div>
          <div className="metric-value">
            {sprDays != null ? Number(sprDays).toFixed(1) : '—'}
          </div>
          <div className="metric-sub">Days of cover remaining</div>
        </div>

        {/* Pipeline latency */}
        <div className="metric-card">
          <div className="metric-label">Pipeline Latency</div>
          <div className="metric-value">
            {latency != null ? `${Number(latency).toFixed(0)}s` : '—'}
          </div>
          <div className="metric-sub">Last end-to-end run</div>
        </div>
      </div>

      {lastRefresh && (
        <div className="last-updated" style={{ marginTop: 6, textAlign: 'right' }}>
          Refreshed {lastRefresh.toLocaleTimeString()} · auto every 30 s
        </div>
      )}
    </div>
  );
}
