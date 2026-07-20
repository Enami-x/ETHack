/**
 * ProcurementTable.jsx
 * Ranked table of procurement_recs for the active scenario.
 * Columns: rank, supplier, overall_score, spot_price_est, transit_time_days,
 * corridor badge (Hormuz-exposed), rationale (truncated with expand).
 */
import { useState, useEffect } from 'react';
import { fetchProcurementRecs } from '../api';

function isHormuzExposed(row) {
  const dep = (row.corridor_dependency ?? row.route ?? '').toLowerCase();
  return dep.includes('hormuz');
}

function ExpandableText({ text = '', limit = 120 }) {
  const [expanded, setExpanded] = useState(false);
  if (!text) return <span style={{ color: 'var(--text-3)', fontStyle: 'italic' }}>—</span>;
  if (text.length <= limit) return <span>{text}</span>;
  return (
    <span>
      {expanded ? text : text.slice(0, limit) + '…'}
      {' '}
      <button className="expand-btn" onClick={() => setExpanded(e => !e)}>
        {expanded ? 'collapse' : 'more'}
      </button>
    </span>
  );
}

export default function ProcurementTable({ scenarioId, activeScenario }) {
  const [recs, setRecs]     = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError]   = useState(null);

  useEffect(() => {
    if (!scenarioId) {
      setRecs([]);
      return;
    }

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchProcurementRecs(scenarioId);
        setRecs(data);
      } catch (e) {
        const is404 = e?.response?.status === 404;
        setError(is404
          ? 'No procurement recommendations yet — run the pipeline.'
          : 'Could not load recommendations. Check that the backend is running.');
        setRecs([]);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [scenarioId]);

  // Determine which corridor is relevant to the active scenario for badge logic
  const scenarioCorridor = activeScenario?.scenario_type?.includes('hormuz') ? 'hormuz'
    : activeScenario?.scenario_type?.includes('red_sea') ? 'red_sea'
    : null;

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Procurement Recommendations</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {activeScenario && (
            <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
              {activeScenario.scenario_type?.replace(/_/g, ' ')}
            </span>
          )}
          {loading && <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Loading…</span>}
        </div>
      </div>

      {/* Empty / error states */}
      {!scenarioId && (
        <div className="state-box">
          <strong>No scenario selected</strong>
          Select a scenario above to view procurement recommendations.
        </div>
      )}

      {scenarioId && error && (
        <div className="state-box">
          <strong>No data yet</strong>
          {error}
        </div>
      )}

      {scenarioId && !error && recs.length === 0 && !loading && (
        <div className="state-box">
          <strong>No recommendations</strong>
          Run the pipeline to generate procurement rankings.
        </div>
      )}

      {recs.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Supplier</th>
                <th>Score</th>
                <th>Spot Price ($/bbl)</th>
                <th>Transit (days)</th>
                <th>Corridor Risk</th>
                <th>Rationale</th>
              </tr>
            </thead>
            <tbody>
              {recs.map(row => (
                <tr key={row.id ?? row.rank}>
                  <td className="rank-num">{row.rank}</td>
                  <td style={{ fontWeight: 500 }}>
                    {row.supplier}
                    {row.route && (
                      <div style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 400 }}>
                        via {row.route}
                      </div>
                    )}
                  </td>
                  <td>
                    <span style={{ fontWeight: 700 }}>
                      {row.overall_score != null ? Number(row.overall_score).toFixed(3) : '—'}
                    </span>
                    {row.refinery_compatibility_score != null && (
                      <div style={{ fontSize: 10, color: 'var(--text-3)' }}>
                        compat {Number(row.refinery_compatibility_score).toFixed(2)}
                      </div>
                    )}
                  </td>
                  <td>{row.spot_price_est != null ? `$${Number(row.spot_price_est).toFixed(1)}` : '—'}</td>
                  <td>{row.transit_time_days != null ? `${row.transit_time_days}d` : '—'}</td>
                  <td>
                    {isHormuzExposed(row)
                      ? <span className="corridor-badge">Hormuz-exposed</span>
                      : <span style={{ fontSize: 11, color: 'var(--text-3)' }}>—</span>}
                  </td>
                  <td style={{ maxWidth: 320 }}>
                    <ExpandableText text={row.rationale} limit={130} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
