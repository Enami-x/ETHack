/**
 * DrawdownChart.jsx
 * Recharts BarChart of a reserve_plan's drawdown_schedule.
 * X-axis = day, Y-axis = draw_pct.
 * Bars are colored by phase: front-loaded days (first ~40%) get a darker fill,
 * taper days get a lighter fill. Fetches from /api/reserve-plan when scenarioId changes.
 */
import { useState, useEffect } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell
} from 'recharts';
import { fetchReservePlan } from '../api';

// Phase threshold: first 40% of schedule days are "front-loaded"
function isEarlyPhase(day, totalDays) {
  return day <= totalDays * 0.4;
}

const FILL_EARLY = '#78716c';   // slate-600 — darker
const FILL_TAPER = '#d6d3d1';   // stone-300 — lighter

export default function DrawdownChart({ scenarioId }) {
  const [schedule, setSchedule] = useState([]);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);

  useEffect(() => {
    if (!scenarioId) {
      setSchedule([]);
      return;
    }

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const plan = await fetchReservePlan(scenarioId);
        setSchedule(plan?.drawdown_schedule ?? []);
      } catch {
        setError('No reserve plan for this scenario yet.');
        setSchedule([]);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [scenarioId]);

  const totalDays = schedule.length ? schedule[schedule.length - 1].day : 0;

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">SPR Drawdown Schedule</span>
        {loading && <span style={{ fontSize: 11, color: 'var(--text-3)' }}>Loading…</span>}
      </div>
      <div className="card-body" style={{ paddingBottom: 8 }}>
        {!scenarioId && (
          <div className="state-box">
            <strong>Select a scenario</strong>
            Choose a scenario above to view its drawdown schedule.
          </div>
        )}

        {scenarioId && error && (
          <div className="state-box">
            <strong>No data yet</strong>
            {error}
          </div>
        )}

        {scenarioId && !error && schedule.length === 0 && !loading && (
          <div className="state-box">
            <strong>No drawdown data</strong>
            Run the pipeline to generate a reserve plan.
          </div>
        )}

        {schedule.length > 0 && (
          <>
            <div className="chart-wrap">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={schedule} barSize={Math.max(4, Math.min(16, 200 / schedule.length))}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                  <XAxis
                    dataKey="day"
                    tick={{ fontSize: 10, fill: 'var(--text-3)' }}
                    tickLine={false}
                    axisLine={false}
                    label={{ value: 'Day', position: 'insideBottomRight', offset: -4, fontSize: 10, fill: 'var(--text-3)' }}
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: 'var(--text-3)' }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={v => `${v}%`}
                    width={38}
                  />
                  <Tooltip
                    formatter={(v) => [`${Number(v).toFixed(2)}%`, 'Draw %']}
                    labelFormatter={(d) => `Day ${d}`}
                    contentStyle={{ fontSize: 12, border: '1px solid var(--border)', borderRadius: 4 }}
                  />
                  <Bar dataKey="draw_pct" radius={[2, 2, 0, 0]}>
                    {schedule.map((entry) => (
                      <Cell
                        key={entry.day}
                        fill={isEarlyPhase(entry.day, totalDays) ? FILL_EARLY : FILL_TAPER}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Phase legend */}
            <div style={{ display: 'flex', gap: 14, marginTop: 6, justifyContent: 'flex-end' }}>
              {[
                { color: FILL_EARLY, label: 'Front-loaded phase' },
                { color: FILL_TAPER, label: 'Taper phase' },
              ].map(({ color, label }) => (
                <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, color: 'var(--text-3)' }}>
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: color, display: 'inline-block' }} />
                  {label}
                </span>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
