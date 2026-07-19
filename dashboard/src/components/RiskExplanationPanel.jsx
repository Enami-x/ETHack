import React from 'react';

const RiskExplanationPanel = ({ selectedCorridor, hormuzRisk, redSeaRisk }) => {
  const getCorridorData = () => {
    if (selectedCorridor === 'hormuz') {
      return {
        name: 'Strait of Hormuz',
        data: hormuzRisk,
      };
    }
    if (selectedCorridor === 'red_sea') {
      return {
        name: 'Red Sea / Bab-el-Mandeb',
        data: redSeaRisk,
      };
    }
    return null;
  };

  const active = getCorridorData();

  const getRiskLabel = (score) => {
    if (score === null || score === undefined) return 'UNKNOWN';
    if (score < 0.4) return 'LOW RISK';
    if (score <= 0.7) return 'ELEVATED RISK';
    return 'CRITICAL RISK';
  };

  const getRiskBadgeClass = (score) => {
    if (score === null || score === undefined) return 'badge-neutral';
    if (score < 0.4) return 'badge-stable';
    if (score <= 0.7) return 'badge-caution';
    return 'badge-critical';
  };

  return (
    <div className="explanation-panel">
      <div className="panel-header border-b">
        <h3 className="panel-title">Geopolitical Risk Intelligence Detail</h3>
        <span className="panel-subtitle">Generative AI analysis and explanation</span>
      </div>

      {active ? (
        <div className="explanation-content">
          <div className="explanation-meta">
            <span className="explanation-corridor">{active.name}</span>
            <div className="meta-stats">
              <span className={`status-badge ${getRiskBadgeClass(active.data?.risk_score)}`}>
                {getRiskLabel(active.data?.risk_score)} ({active.data?.risk_score?.toFixed(2) || 'N/A'})
              </span>
              <span className="confidence-label">
                Confidence: {active.data?.confidence ? `${(active.data.confidence * 100).toFixed(0)}%` : 'N/A'}
              </span>
              <span className="timestamp-label">
                Analyzed at: {active.data?.generated_at ? new Date(active.data.generated_at).toLocaleString() : 'N/A'}
              </span>
            </div>
          </div>
          
          <div className="explanation-text-wrapper">
            <p className="explanation-narrative">
              {active.data?.explanation || 'No detail analysis text available for this corridor.'}
            </p>
          </div>

          {active.data?.contributing_signals && active.data.contributing_signals.length > 0 && (
            <div className="signals-linked">
              <span className="signals-title">Contributing Signals ({active.data.contributing_signals.length}):</span>
              <div className="signals-badges">
                {active.data.contributing_signals.map((sigId, i) => (
                  <span key={i} className="signal-id-badge">
                    {sigId.substring(0, 8)}...
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="no-selection-msg">
          <svg className="info-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p>Please click a corridor marker on the map to display the live AI-generated risk intelligence report.</p>
        </div>
      )}
    </div>
  );
};

export default RiskExplanationPanel;
