import React from 'react';

const ScenarioPanel = ({ scenarios, activeScenario, activeReservePlan, onSelectScenarioType }) => {
  const scenarioTypes = [
    { type: 'hormuz_partial_closure', label: 'Hormuz Closure' },
    { type: 'opec_emergency_cut', label: 'OPEC+ Cut' },
    { type: 'red_sea_suspension', label: 'Red Sea Suspension' },
  ];

  const parsePolicyStatus = (policyText) => {
    if (!policyText) return 'STABLE';
    const text = policyText.toUpperCase();
    if (text.includes('CRITICAL')) return 'CRITICAL';
    if (text.includes('CAUTION') || text.includes('WARNING')) return 'CAUTION';
    return 'STABLE';
  };

  const getBadgeClass = (status) => {
    switch (status) {
      case 'CRITICAL':
        return 'badge-critical';
      case 'CAUTION':
        return 'badge-caution';
      default:
        return 'badge-stable';
    }
  };

  const policyText = activeReservePlan?.policy_recommendation || '';
  const policyStatus = parsePolicyStatus(policyText);
  const badgeClass = getBadgeClass(policyStatus);

  return (
    <div className="scenario-panel">
      <div className="panel-header">
        <h3 className="panel-title">Geopolitical Scenario Explorer</h3>
        <span className="panel-subtitle">Simulate supply chain shock impacts</span>
      </div>

      {/* Tabs */}
      <div className="scenario-tabs">
        {scenarioTypes.map((tab) => {
          const isSelected = activeScenario?.scenario_type === tab.type;
          return (
            <button
              key={tab.type}
              className={`tab-btn ${isSelected ? 'active' : ''}`}
              onClick={() => onSelectScenarioType(tab.type)}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {activeScenario ? (
        <div className="scenario-details">
          {/* Metrics grid */}
          <div className="scenario-grid">
            <div className="grid-item">
              <span className="grid-label">Scenario Severity</span>
              <span className="grid-val">{(activeScenario.severity * 100).toFixed(0)}%</span>
            </div>
            <div className="grid-item">
              <span className="grid-label">Supply Gap</span>
              <span className="grid-val">{(activeScenario.supply_gap_pct * 100).toFixed(1)}%</span>
            </div>
            <div className="grid-item">
              <span className="grid-label">Price Impact</span>
              <span className="grid-val">+{activeScenario.price_impact_pct.toFixed(1)}%</span>
            </div>
            {activeScenario.refinery_utilization_impact_pct !== undefined && (
              <div className="grid-item">
                <span className="grid-label">Refinery Impact</span>
                <span className="grid-val">{activeScenario.refinery_utilization_impact_pct.toFixed(1)}%</span>
              </div>
            )}
          </div>

          {/* Policy Recommendations */}
          <div className="policy-section">
            <div className="policy-header">
              <h4 className="section-title">Strategic Response</h4>
              <span className={`status-badge ${badgeClass}`}>{policyStatus}</span>
            </div>
            <p className="policy-text">
              {policyText || 'Generating recommendations based on strategic reserves and gap analysis...'}
            </p>
          </div>

          {/* Model Assumptions */}
          {activeScenario.assumptions && activeScenario.assumptions.length > 0 && (
            <div className="assumptions-section">
              <h4 className="section-title">Model Assumptions</h4>
              <ul className="assumptions-list">
                {activeScenario.assumptions.map((asm, idx) => (
                  <li key={idx}>{asm}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <div className="no-data-msg">
          No data available for this scenario. Please run the pipeline.
        </div>
      )}
    </div>
  );
};

export default ScenarioPanel;
