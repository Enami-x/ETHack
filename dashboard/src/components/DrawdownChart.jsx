import React from 'react';
import { BarChart, Bar, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';

const DrawdownChart = ({ activeReservePlan, activeScenario }) => {
  const schedule = activeReservePlan?.drawdown_schedule || [];
  const windowDays = schedule.length;

  const parsePolicyStatus = (policyText) => {
    if (!policyText) return 'STABLE';
    const text = policyText.toUpperCase();
    if (text.includes('CRITICAL')) return 'CRITICAL';
    if (text.includes('CAUTION') || text.includes('WARNING')) return 'CAUTION';
    return 'STABLE';
  };

  const policyText = activeReservePlan?.policy_recommendation || '';
  const status = parsePolicyStatus(policyText);

  // Define colors for each status and phase
  const colorMap = {
    CRITICAL: {
      p1: '#991b1b', // dark red
      p2: '#dc2626', // medium red
      p3: '#fca5a5', // light red
    },
    CAUTION: {
      p1: '#92400e', // dark amber
      p2: '#d97706', // medium amber
      p3: '#fde047', // light amber
    },
    STABLE: {
      p1: '#065f46', // dark green
      p2: '#059669', // medium green
      p3: '#6ee7b7', // light green
    },
  };

  const getCellColor = (day, totalDays) => {
    const colors = colorMap[status] || colorMap.STABLE;
    if (totalDays <= 0) return colors.p2;

    const p1End = Math.floor(totalDays / 3);
    const p2End = Math.floor((2 * totalDays) / 3);

    if (day <= p1End) return colors.p1;
    if (day <= p2End) return colors.p2;
    return colors.p3;
  };

  const chartData = schedule.map((item) => ({
    dayLabel: `Day ${item.day}`,
    day: item.day,
    drawPercent: Number((item.draw_pct * 100).toFixed(2)),
  }));

  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="chart-tooltip">
          <p className="tooltip-day">{data.dayLabel}</p>
          <p className="tooltip-value">Drawdown: {data.drawPercent}%</p>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="drawdown-chart-panel">
      <div className="panel-header">
        <h3 className="panel-title">Strategic Petroleum Reserve (SPR) Drawdown</h3>
        <span className="panel-subtitle">Day-by-day depletion scheduling</span>
      </div>

      <div className="chart-wrapper" style={{ width: '100%', height: '240px', marginTop: '16px' }}>
        {chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={chartData}
              margin={{ top: 10, right: 10, left: -25, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
              <XAxis 
                dataKey="day" 
                stroke="#737373" 
                tick={{ fill: '#a3a3a3', fontSize: 11 }}
                tickLine={{ stroke: '#404040' }}
              />
              <YAxis 
                stroke="#737373" 
                tick={{ fill: '#a3a3a3', fontSize: 11 }}
                tickLine={{ stroke: '#404040' }}
                unit="%"
              />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255, 255, 255, 0.03)' }} />
              <Bar dataKey="drawPercent">
                {chartData.map((entry, index) => (
                  <Cell 
                    key={`cell-${index}`} 
                    fill={getCellColor(entry.day, windowDays)} 
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="no-data-msg" style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            No drawdown schedule available. Run the pipeline.
          </div>
        )}
      </div>
      {chartData.length > 0 && (
        <div className="chart-legend">
          <div className="legend-item">
            <span className="legend-dot" style={{ backgroundColor: colorMap[status]?.p1 }} />
            <span>Phase 1 (Front-Loaded)</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot" style={{ backgroundColor: colorMap[status]?.p2 }} />
            <span>Phase 2 (Mid-disruption)</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot" style={{ backgroundColor: colorMap[status]?.p3 }} />
            <span>Phase 3 (Taper/Recovery)</span>
          </div>
        </div>
      )}
    </div>
  );
};

export default DrawdownChart;
