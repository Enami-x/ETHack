/**
 * ScenarioPanel.jsx
 * Three tab buttons for the 3 scenario types.
 * Selecting one fetches and shows severity, supply_gap_pct, price_impact_pct,
 * a policy status badge (parsed from policy_recommendation text), and the full
 * policy_recommendation. Calls onScenarioChange(scenario) so App can wire
 * DrawdownChart and ProcurementTable.
 */
import { useState, useEffect } from 'react';
import { fetchScenarios, fetchReservePlan } from '../api';

const SCENARIO_TYPES = [
  { key: 'hormuz_partial_closure', label: 'Hormuz Closure' },
  { key: 'opec_emergency_cut',     label: 'OPEC+ Cut'      },
  { key: 'red_sea_suspension',     label: 'Red Sea Susp.'  },
];

function parsePolicyStatus(text = '') {
  const upper = text.toUpperCase();
  if (upper.includes('CRITICAL')) return 'critical';
  if (upper.includes('CAUTION'))  return 'caution';
  return 'stable';
}

function pct(v) {
  if (v == null) return '—';
  return `${Number(v).toFixed(1)}%`;
}

export default function ScenarioPanel({ onScenarioChange }) {
  const [scenarios, setScenarios]       = useState({});
  const [activeType, setActiveType]     = useState(SCENARIO_TYPES[0].key);
  const [reservePlan, setReservePlan]   = useState(null);
  const [loading, setLoading]           = useState(false);
  const [error, setError]               = useState(null);

  // Load all scenarios once
  useEffect(() => {
    async function load() {
      try {
        const data = await fetchScenarios();
        const map = {};
        data.forEach(s => { map[s.scenario_type] = s; });
        setScenarios(map);
      } catch {
        setError('Could not load scenarios — is the backend running?');
      }
    }
    load();
  }, []);

  // When active scenario changes, fetch its reserve plan and notify parent
  const activeScenario = scenarios[activeType];

  useEffect(() => {
    if (!activeScenario) return;
    onScenarioChange && onScenarioChange(activeScenario);

    async function loadPlan() {
      setLoading(true);
      try {
        const plan = await fetchReservePlan(activeScenario.id);
        setReservePlan(plan);
      } catch {
        setReservePlan(null);
      } finally {
        setLoading(false);
      }
    }
    loadPlan();
  }, [activeScenario?.id]);

  const policyText = reservePlan?.policy_recommendation ?? activeScenario?.assumptions?.join(' ') ?? '';
  const status     = parsePolicyStatus(policyText);

  const statusLabel = { stable: 'STABLE', caution: 'CAUTION', critical: 'CRITICAL' };

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Scenario Explorer</span>
        {loading && <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Loading…</span>}
      </div>
      <div className="card-body">
        {/* Tabs */}
        <div className="scenario-tabs">
          {SCENARIO_TYPES.map(({ key, label }) => (
            <button
              key={key}
              className={`scenario-tab${activeType === key ? ' active' : ''}`}
              onClick={() => setActiveType(key)}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Content */}
        {error && !activeScenario && (
          <div className="state-box">
            <strong>No data yet</strong>
            {error}
          </div>
        )}

        {!activeScenario && !error && (
          <div className="state-box">
            <strong>No data yet</strong>
            Run the pipeline to populate scenarios.
          </div>
        )}

        {activeScenario && (
          <>
            <div className="scenario-grid" style={{ marginTop: 14 }}>
              <div>
                <div className="scenario-stat-label">Severity</div>
                <div className="scenario-stat-value">{pct(activeScenario.severity)}</div>
              </div>
              <div>
                <div className="scenario-stat-label">Supply Gap</div>
                <div className="scenario-stat-value">{pct(activeScenario.supply_gap_pct)}</div>
              </div>
              <div>
                <div className="scenario-stat-label">Price Impact</div>
                <div className="scenario-stat-value">{pct(activeScenario.price_impact_pct)}</div>
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
              <span style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 500 }}>Policy status:</span>
              <span className={`policy-badge ${status}`}>{statusLabel[status]}</span>
            </div>

            {policyText && (
              <div className="policy-text">{policyText}</div>
            )}

            {activeScenario.assumptions?.length > 0 && (
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 10, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 4 }}>
                  Explicit Assumptions
                </div>
                <ul style={{ paddingLeft: 16, fontSize: 12, color: 'var(--text-2)', lineHeight: 1.6 }}>
                  {activeScenario.assumptions.map((a, i) => <li key={i}>{a}</li>)}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
