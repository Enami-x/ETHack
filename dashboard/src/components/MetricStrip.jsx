import React from 'react';

const MetricStrip = ({ hormuzRisk, redSeaRisk, sprDaysRemaining, pipelineLatency }) => {
  const getRiskColor = (score) => {
    if (score === null || score === undefined) return 'text-neutral-400';
    if (score < 0.4) return 'text-emerald-500';
    if (score <= 0.7) return 'text-amber-500';
    return 'text-rose-500';
  };

  const formatRiskScore = (score) => {
    if (score === null || score === undefined) return 'N/A';
    return score.toFixed(2);
  };

  return (
    <div className="metric-strip-container">
      {/* Hormuz Strait Risk */}
      <div className="metric-card">
        <div className="metric-card-header">
          <span className="metric-card-title">Hormuz Strait Risk</span>
          <span className="metric-card-subtitle">Probability of Disruption</span>
        </div>
        <div className={`metric-card-value ${getRiskColor(hormuzRisk?.risk_score)}`}>
          {formatRiskScore(hormuzRisk?.risk_score)}
        </div>
        <div className="metric-card-footer">
          Confidence: {hormuzRisk?.confidence ? `${(hormuzRisk.confidence * 100).toFixed(0)}%` : 'N/A'}
        </div>
      </div>

      {/* Red Sea / Bab-el-Mandeb Risk */}
      <div className="metric-card">
        <div className="metric-card-header">
          <span className="metric-card-title">Red Sea Corridor Risk</span>
          <span className="metric-card-subtitle">Probability of Disruption</span>
        </div>
        <div className={`metric-card-value ${getRiskColor(redSeaRisk?.risk_score)}`}>
          {formatRiskScore(redSeaRisk?.risk_score)}
        </div>
        <div className="metric-card-footer">
          Confidence: {redSeaRisk?.confidence ? `${(redSeaRisk.confidence * 100).toFixed(0)}%` : 'N/A'}
        </div>
      </div>

      {/* SPR Days Remaining */}
      <div className="metric-card">
        <div className="metric-card-header">
          <span className="metric-card-title">Strategic Petroleum Reserve</span>
          <span className="metric-card-subtitle">Remaining Cover Days</span>
        </div>
        <div className="metric-card-value text-sky-400">
          {sprDaysRemaining !== null && sprDaysRemaining !== undefined ? sprDaysRemaining : 'N/A'}
        </div>
        <div className="metric-card-footer">
          Based on highest severity scenario
        </div>
      </div>

      {/* Pipeline Latency */}
      <div className="metric-card">
        <div className="metric-card-header">
          <span className="metric-card-title">Pipeline Status</span>
          <span className="metric-card-subtitle">Last Run Latency</span>
        </div>
        <div className="metric-card-value text-purple-400">
          {pipelineLatency !== null && pipelineLatency !== undefined 
            ? `${pipelineLatency.toFixed(2)}s` 
            : 'N/A'}
        </div>
        <div className="metric-card-footer">
          Refreshes automatically every 30s
        </div>
      </div>
    </div>
  );
};

export default MetricStrip;
