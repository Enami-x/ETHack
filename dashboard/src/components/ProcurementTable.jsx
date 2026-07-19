import React, { useState } from 'react';

const ProcurementTable = ({ recommendations, activeScenario }) => {
  const [expandedRow, setExpandedRow] = useState(null);

  const CORRIDOR_DEPENDENCIES = {
    'UAE': ['hormuz'],
    'Saudi Arabia': ['hormuz'],
    'Iraq': ['hormuz']
  };

  const getActiveCorridor = (scenarioType) => {
    if (scenarioType === 'hormuz_partial_closure') return 'hormuz';
    if (scenarioType === 'red_sea_suspension') return 'red_sea';
    return null;
  };

  const activeCorridor = activeScenario ? getActiveCorridor(activeScenario.scenario_type) : null;

  const toggleExpand = (rowId) => {
    setExpandedRow(expandedRow === rowId ? null : rowId);
  };

  return (
    <div className="procurement-panel">
      <div className="panel-header">
        <h3 className="panel-title">Alternative Source Procurement Ranking</h3>
        <span className="panel-subtitle">Risk-adjusted sourcing options sorted by overall score</span>
      </div>

      <div className="table-wrapper">
        {recommendations && recommendations.length > 0 ? (
          <table className="procurement-table">
            <thead>
              <tr>
                <th style={{ width: '60px' }}>Rank</th>
                <th>Supplier</th>
                <th>Route / Transit Mode</th>
                <th style={{ textAlign: 'right' }}>Compatibility</th>
                <th style={{ textAlign: 'right' }}>Est. Price</th>
                <th style={{ textAlign: 'right' }}>Transit Time</th>
                <th style={{ textAlign: 'right' }}>Score</th>
                <th style={{ width: '100px', textAlign: 'center' }}>Status</th>
                <th style={{ width: '80px', textAlign: 'center' }}>Details</th>
              </tr>
            </thead>
            <tbody>
              {recommendations.map((rec) => {
                const isRowExpanded = expandedRow === rec.id;
                const deps = CORRIDOR_DEPENDENCIES[rec.supplier] || [];
                const isExposed = activeCorridor && deps.includes(activeCorridor);
                const displayScore = rec.overall_score.toFixed(4);

                return (
                  <React.Fragment key={rec.id}>
                    <tr className={`table-row ${isExposed ? 'row-exposed' : ''}`}>
                      <td className="rank-cell">#{rec.rank}</td>
                      <td className="supplier-name">{rec.supplier}</td>
                      <td className="route-cell">{rec.route || 'Direct shipping'}</td>
                      <td className="number-cell">
                        {(rec.refinery_compatibility_score * 100).toFixed(0)}%
                      </td>
                      <td className="number-cell">${rec.spot_price_est.toFixed(2)}/bbl</td>
                      <td className="number-cell">{rec.transit_time_days} days</td>
                      <td className="number-cell highlight-score">{displayScore}</td>
                      <td className="badge-cell">
                        {isExposed ? (
                          <span className="exposure-badge badge-red">Hormuz-exposed</span>
                        ) : (
                          <span className="exposure-badge badge-green">Protected</span>
                        )}
                      </td>
                      <td className="action-cell">
                        <button className="expand-row-btn" onClick={() => toggleExpand(rec.id)}>
                          {isRowExpanded ? 'Hide' : 'Show'}
                        </button>
                      </td>
                    </tr>
                    {isRowExpanded && (
                      <tr className="expansion-row">
                        <td colSpan={9}>
                          <div className="rationale-panel">
                            <strong>Detailed Sourcing Rationale:</strong>
                            <p>{rec.rationale}</p>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        ) : (
          <div className="no-data-msg">
            No procurement recommendations available. Select a scenario and run the pipeline.
          </div>
        )}
      </div>
    </div>
  );
};

export default ProcurementTable;
