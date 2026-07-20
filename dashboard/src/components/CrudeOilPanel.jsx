/**
 * CrudeOilPanel.jsx
 *
 * Live EIA crude oil data panel showing:
 *  - Brent & WTI current price + daily % change
 *  - US crude inventory + refinery utilisation
 *  - 30-day Brent vs WTI price chart (Recharts)
 *  - Data source badge (live / cached / unavailable)
 *
 * Auto-refreshes every 60 s.
 */
import { useState, useEffect, useCallback } from 'react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from 'recharts';
import { fetchCrudeOil } from '../api';

// ── Helpers ────────────────────────────────────────────────────────────────

function pctColor(pct) {
  if (pct == null) return 'var(--text-3)';
  if (pct > 1)  return 'var(--risk-high)';
  if (pct > 0)  return 'var(--risk-mid)';
  if (pct < -1) return 'var(--risk-low)';
  return 'var(--text-2)';
}

function fmtPct(pct) {
  if (pct == null) return '—';
  return `${pct > 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

function fmtNum(n, decimals = 2) {
  if (n == null) return '—';
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function SourceBadge({ source }) {
  const map = {
    eia_live:        { label: 'EIA Live',    color: 'var(--olive)' },
    eia_cache:       { label: 'EIA Cached',  color: 'var(--gold)' },
    eia_unavailable: { label: 'Unavailable', color: 'var(--text-3)' },
  };
  const { label, color } = map[source] ?? { label: source ?? '—', color: 'var(--text-3)' };
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, letterSpacing: '.05em',
      color, borderRadius: 4, padding: '2px 7px',
      background: color + '22',
      textTransform: 'uppercase',
    }}>
      ● {label}
    </span>
  );
}

function PriceBlock({ label, price, pct, sub }) {
  return (
    <div style={{ minWidth: 110 }}>
      <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.07em', color: 'var(--text-3)', textTransform: 'uppercase', marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-.03em', color: 'var(--brown)', lineHeight: 1 }}>
        {price != null ? `$${fmtNum(price)}` : '—'}
      </div>
      {pct != null && (
        <div style={{ fontSize: 12, fontWeight: 600, color: pctColor(pct), marginTop: 4 }}>
          {fmtPct(pct)} <span style={{ fontWeight: 400, color: 'var(--text-3)' }}>1d</span>
        </div>
      )}
      {sub && <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function InventoryBlock({ label, value, unit, trend }) {
  const trendIcons = { building: '▲', drawing: '▼', stable: '→' };
  const trendColors = { building: 'var(--risk-mid)', drawing: 'var(--risk-low)', stable: 'var(--text-3)' };
  return (
    <div style={{ minWidth: 110 }}>
      <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.07em', color: 'var(--text-3)', textTransform: 'uppercase', marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--brown)', lineHeight: 1 }}>
        {value != null ? fmtNum(value, 0) : '—'}
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
        {unit}
        {trend && (
          <span style={{ marginLeft: 6, color: trendColors[trend], fontWeight: 700 }}>
            {trendIcons[trend]} {trend}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Chart tooltip ──────────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 6, padding: '8px 12px', fontSize: 12, boxShadow: 'var(--shadow-lg)',
    }}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: 'var(--text-2)' }}>{label}</div>
      {payload.map(p => (
        <div key={p.name} style={{ color: p.color, fontWeight: 500 }}>
          {p.name}: <strong>${p.value?.toFixed(2) ?? '—'}</strong>
        </div>
      ))}
    </div>
  );
}

// ── Merge Brent + WTI series into chart data ────────────────────────────────

function mergeSeriesForChart(brentSeries, wtiSeries) {
  const map = {};
  (brentSeries ?? []).forEach(({ date, price }) => {
    if (!map[date]) map[date] = { date };
    map[date].brent = price;
  });
  (wtiSeries ?? []).forEach(({ date, price }) => {
    if (!map[date]) map[date] = { date };
    map[date].wti = price;
  });
  return Object.values(map).sort((a, b) => a.date.localeCompare(b.date));
}

// ── Main component ─────────────────────────────────────────────────────────

export default function CrudeOilPanel() {
  const [data,        setData]        = useState(null);
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);

  const load = useCallback(async () => {
    try {
      const snap = await fetchCrudeOil();
      setData(snap);
      setError(null);
    } catch (err) {
      setError('EIA data unavailable');
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, [load]);

  const chartData = data ? mergeSeriesForChart(data.brent_series, data.wti_series) : [];

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">🛢️ Crude Oil Markets — EIA Live Data</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {data && <SourceBadge source={data.data_source} />}
          {lastRefresh && (
            <span style={{ fontSize: 10, color: 'var(--text-3)' }}>
              {lastRefresh.toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      <div className="card-body">
        {loading && (
          <div className="state-box">
            <div className="spinner" style={{ margin: '0 auto 8px', borderTopColor: 'var(--olive)', border: '2px solid var(--border)' }} />
            Fetching EIA data…
          </div>
        )}

        {error && !loading && (
          <div className="state-box">
            <strong>⚠ {error}</strong>
            Check that <code>EIA_API_KEY</code> is set in your <code>.env</code> file.
          </div>
        )}

        {data && !loading && (
          <>
            {/* ── Price row ──────────────────────────────────────── */}
            <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap', marginBottom: 20, paddingBottom: 16, borderBottom: '1px solid var(--border)' }}>
              <PriceBlock
                label="Brent Crude (FOB)"
                price={data.brent_usd}
                pct={data.brent_pct_change}
                sub="Europe spot price"
              />
              <PriceBlock
                label="WTI Cushing (FOB)"
                price={data.wti_usd}
                pct={data.wti_pct_change}
                sub="US benchmark"
              />
              <div style={{ width: 1, background: 'var(--border)', alignSelf: 'stretch' }} />
              <InventoryBlock
                label="US Crude Stocks"
                value={data.inventory_kb}
                unit="thousand barrels (weekly)"
                trend={data.inventory_trend}
              />
              <InventoryBlock
                label="Refinery Inputs"
                value={data.refinery_inputs_kbd}
                unit="kb/day (weekly)"
                trend={null}
              />
            </div>

            {/* ── 30-day price chart ──────────────────────────────── */}
            {chartData.length > 0 && (
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-3)', marginBottom: 10 }}>
                  30-Day Price History ($/bbl)
                </div>
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis
                      dataKey="date"
                      tick={{ fontSize: 10, fill: 'var(--text-3)' }}
                      tickFormatter={d => d?.slice(5)}   /* MM-DD */
                      interval={6}
                    />
                    <YAxis
                      domain={['auto', 'auto']}
                      tick={{ fontSize: 10, fill: 'var(--text-3)' }}
                      tickFormatter={v => `$${v}`}
                      width={45}
                    />
                    <Tooltip content={<ChartTooltip />} />
                    <Legend
                      iconType="circle"
                      wrapperStyle={{ fontSize: 11, paddingTop: 6 }}
                    />
                    <Line
                      type="monotone"
                      dataKey="brent"
                      name="Brent"
                      stroke="var(--olive)"
                      strokeWidth={2}
                      dot={false}
                      activeDot={{ r: 4 }}
                    />
                    <Line
                      type="monotone"
                      dataKey="wti"
                      name="WTI"
                      stroke="var(--amber)"
                      strokeWidth={2}
                      dot={false}
                      activeDot={{ r: 4 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* ── Disclaimer ─────────────────────────────────────── */}
            <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
              Source: U.S. Energy Information Administration (EIA) API v2 · Brent: RBRTE · WTI: RWTC · Stocks: WTTSTUS
            </div>
          </>
        )}
      </div>
    </div>
  );
}
