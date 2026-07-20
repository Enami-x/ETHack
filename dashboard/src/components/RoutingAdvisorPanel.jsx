/**
 * RoutingAdvisorPanel.jsx
 *
 * Full interactive route recommendation system:
 *   Step 1 — Input form (origin + destination port selectors + live Brent price)
 *   Step 2 — Loading / assessment animation
 *   Step 3 — Ranked recommendation cards with geopolitical context + rationale
 *   Step 4 — Accepted: animated route map + decision walkthrough + cost breakdown
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip as RTooltip, Cell, Legend,
} from 'recharts';
import { assessRoute, fetchCrudeOil } from '../api';
import SVGWorldMap from './SVGWorldMap';

// ─────────────────────────────────────────────────────────────────────────────
// Static port data (mirrors backend PORTS dict — used for fast UI render
// before the API call, no extra round-trip needed)
// ─────────────────────────────────────────────────────────────────────────────
const PORTS = [
  { id: 'ras_tanura',   name: 'Ras Tanura, Saudi Arabia',    region: 'Persian Gulf',    flag: '🇸🇦' },
  { id: 'yanbu',        name: 'Yanbu, Saudi Arabia',          region: 'Red Sea',         flag: '🇸🇦' },
  { id: 'fujairah',     name: 'Fujairah, UAE',                region: 'Gulf of Oman',    flag: '🇦🇪' },
  { id: 'basrah',       name: 'Basrah, Iraq',                 region: 'Persian Gulf',    flag: '🇮🇶' },
  { id: 'kuwait_city',  name: 'Kuwait City, Kuwait',          region: 'Persian Gulf',    flag: '🇰🇼' },
  { id: 'houston',      name: 'Houston, USA',                 region: 'Gulf of Mexico',  flag: '🇺🇸' },
  { id: 'rotterdam',    name: 'Rotterdam, Netherlands',       region: 'North Sea',       flag: '🇳🇱' },
  { id: 'singapore',    name: 'Singapore',                    region: 'SE Asia',         flag: '🇸🇬' },
  { id: 'novorossiysk', name: 'Novorossiysk, Russia',        region: 'Black Sea',       flag: '🇷🇺' },
  { id: 'vadinar',      name: 'Vadinar, India',               region: 'Indian Ocean',    flag: '🇮🇳' },
  { id: 'chennai',      name: 'Chennai, India',               region: 'Indian Ocean',    flag: '🇮🇳' },
  { id: 'mumbai',       name: 'Mumbai (JNPT), India',         region: 'Indian Ocean',    flag: '🇮🇳' },
];

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
function fmtCost(n) {
  if (n == null) return '—';
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000)     return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n}`;
}

function riskColor(score) {
  if (score == null) return '#6b7280';
  if (score < 0.35)  return '#16a34a';
  if (score < 0.60)  return '#d97706';
  if (score < 0.80)  return '#ea580c';
  return '#dc2626';
}

function riskLabel(score) {
  if (score == null) return 'Unknown';
  if (score < 0.35)  return 'Low';
  if (score < 0.60)  return 'Moderate';
  if (score < 0.80)  return 'High';
  return 'Critical';
}

function recBadge(rec) {
  const map = {
    highly_recommended: { label: '✅ Highly Recommended', cls: 'rec-badge--recommended' },
    conditional:        { label: '⚠️ Conditional',        cls: 'rec-badge--conditional' },
    not_recommended:    { label: '❌ Not Recommended',     cls: 'rec-badge--not-recommended' },
  };
  return map[rec] ?? { label: rec, cls: '' };
}


// ─────────────────────────────────────────────────────────────────────────────
// Sub-panels
// ─────────────────────────────────────────────────────────────────────────────
function PortSelect({ label, value, onChange, exclude }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const ref = useRef(null);

  const filtered = PORTS.filter(p =>
    p.id !== exclude &&
    (p.name.toLowerCase().includes(query.toLowerCase()) ||
     p.region.toLowerCase().includes(query.toLowerCase()))
  );

  const selected = PORTS.find(p => p.id === value);

  // Close on outside click
  useEffect(() => {
    function handler(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div className="port-select" ref={ref}>
      <div className="port-select__label">{label}</div>
      <div
        className={`port-select__trigger ${open ? 'open' : ''}`}
        onClick={() => setOpen(o => !o)}
        id={`port-select-${label.toLowerCase().replace(/\s/g, '-')}`}
      >
        {selected ? (
          <span>{selected.flag} {selected.name} <span className="port-region">{selected.region}</span></span>
        ) : (
          <span className="placeholder">Select port…</span>
        )}
        <span className="port-select__arrow">{open ? '▲' : '▼'}</span>
      </div>
      {open && (
        <div className="port-select__dropdown">
          <input
            autoFocus
            className="port-select__search"
            placeholder="Search ports…"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          <div className="port-select__options">
            {filtered.map(p => (
              <div
                key={p.id}
                className={`port-option ${value === p.id ? 'selected' : ''}`}
                onClick={() => { onChange(p.id); setOpen(false); setQuery(''); }}
              >
                <span className="port-flag">{p.flag}</span>
                <div>
                  <div className="port-name">{p.name}</div>
                  <div className="port-region">{p.region}</div>
                </div>
              </div>
            ))}
            {filtered.length === 0 && (
              <div className="port-option" style={{ color: 'var(--text-3)', fontStyle: 'italic' }}>
                No ports match "{query}"
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function LoadingStage({ label, done }) {
  return (
    <div className="load-stage">
      {done ? (
        <span className="load-stage__check">✓</span>
      ) : (
        <span className="spinner load-stage__spinner" />
      )}
      <span className={done ? 'load-stage__text done' : 'load-stage__text'}>{label}</span>
    </div>
  );
}

function CostBreakdownChart({ option }) {
  const data = [
    { name: 'Fuel',       value: option.fuel_cost_usd,         color: '#f59e0b' },
    { name: 'Operations', value: option.ops_cost_usd,          color: '#6366f1' },
    { name: 'Tolls',      value: option.toll_cost_usd,         color: '#10b981' },
    { name: 'Insurance',  value: option.insurance_premium_usd, color: '#ef4444' },
  ].filter(d => d.value > 0);

  const CustomTooltip = ({ active, payload }) => {
    if (!active || !payload?.length) return null;
    return (
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 12px', fontSize: 12 }}>
        <div style={{ fontWeight: 700 }}>{payload[0].name}</div>
        <div style={{ color: payload[0].payload.color }}>{fmtCost(payload[0].value)}</div>
      </div>
    );
  };

  return (
    <div className="cost-chart">
      <div className="cost-chart__title">Cost Breakdown — {option.name}</div>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="name" tick={{ fontSize: 11, fill: 'var(--text-3)' }} />
          <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}K`} tick={{ fontSize: 10, fill: 'var(--text-3)' }} width={55} />
          <RTooltip content={<CustomTooltip />} />
          <Bar dataKey="value" radius={[4, 4, 0, 0]}>
            {data.map((entry, i) => <Cell key={i} fill={entry.color} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="cost-chart__total">
        Total Voyage Cost: <strong>{fmtCost(option.total_cost_usd)}</strong>
        &nbsp;·&nbsp;
        Cost per barrel: <strong>${(option.total_cost_usd / 1_000_000).toFixed(2)}/bbl</strong>
      </div>
    </div>
  );
}

function RationalePanel({ markdown }) {
  const [expanded, setExpanded] = useState(false);
  // Simple markdown → HTML (bold, headers, bullets, horizontal rules, code)
  const rendered = markdown
    .replace(/^## (.+)$/gm, '<h3 class="rat-h3">$1</h3>')
    .replace(/^### (.+)$/gm, '<h4 class="rat-h4">$1</h4>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^---$/gm, '<hr class="rat-hr"/>')
    .replace(/^\| (.+) \|$/gm, '') // strip tables for now (shown in chart)
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>\n?)+/gs, m => `<ul class="rat-ul">${m}</ul>`)
    .replace(/\n{2,}/g, '</p><p class="rat-p">')
    .replace(/^(?!<[huplHUPL])(.+)$/gm, '<p class="rat-p">$1</p>');

  const preview = markdown.slice(0, 400) + (markdown.length > 400 ? '…' : '');

  return (
    <div className="rationale-panel">
      <div className="rationale-panel__header">
        🤖 AI Decision Walkthrough
        <button
          className="rationale-toggle"
          onClick={() => setExpanded(e => !e)}
        >
          {expanded ? 'Collapse ▲' : 'Expand ▼'}
        </button>
      </div>
      <div
        className={`rationale-panel__body ${expanded ? 'expanded' : ''}`}
        dangerouslySetInnerHTML={{ __html: expanded ? rendered : preview.replace(/\n/g, '<br>') }}
      />
    </div>
  );
}

function RecommendationCard({ option, rank, onAccept, isAccepted }) {
  const [showContext, setShowContext] = useState(false);
  const badge = recBadge(option.recommendation);
  const isPrimary = option.recommendation === 'highly_recommended';

  return (
    <div className={`rec-card ${isPrimary ? 'rec-card--primary' : ''} ${isAccepted ? 'rec-card--accepted' : ''}`}>
      <div className="rec-card__top">
        <div>
          <div className="rec-card__rank">Route #{rank + 1}</div>
          <div className="rec-card__name">{option.name}</div>
        </div>
        <span className={`rec-badge ${badge.cls}`}>{badge.label}</span>
      </div>

      {/* Key metrics */}
      <div className="rec-card__metrics">
        <div className="rec-metric">
          <div className="rec-metric__label">Distance</div>
          <div className="rec-metric__value">{option.distance_nm?.toLocaleString()} NM</div>
        </div>
        <div className="rec-metric">
          <div className="rec-metric__label">Transit</div>
          <div className="rec-metric__value">{option.days} days</div>
        </div>
        <div className="rec-metric">
          <div className="rec-metric__label">Risk Score</div>
          <div className="rec-metric__value" style={{ color: riskColor(option.risk_score) }}>
            {option.risk_score?.toFixed(3)} <span style={{ fontSize: 10, fontWeight: 400 }}>({riskLabel(option.risk_score)})</span>
          </div>
        </div>
        <div className="rec-metric">
          <div className="rec-metric__label">Total Cost</div>
          <div className="rec-metric__value">{fmtCost(option.total_cost_usd)}</div>
        </div>
      </div>

      {/* Corridors */}
      {option.corridors_crossed?.length > 0 && (
        <div className="rec-card__corridors">
          {option.corridors_crossed.map(c => (
            <span key={c} className="corridor-tag">
              ⚠️ {c.replace('_', ' ')}
            </span>
          ))}
        </div>
      )}

      {/* Geopolitical context toggle */}
      <button
        className="context-toggle"
        onClick={() => setShowContext(s => !s)}
      >
        {showContext ? '▲ Hide situation' : '▼ Show geopolitical situation'}
      </button>
      {showContext && (
        <div className="geo-context">
          {option.geopolitical_context}
        </div>
      )}

      {/* Cost mini-breakdown */}
      <div className="cost-mini">
        <span>⛽ {fmtCost(option.fuel_cost_usd)}</span>
        <span>🏛️ {fmtCost(option.toll_cost_usd)}</span>
        <span>🛡️ {fmtCost(option.insurance_premium_usd)}</span>
        <span style={{ color: 'var(--text-3)' }}>⚙️ {fmtCost(option.ops_cost_usd)}</span>
      </div>

      {isPrimary && !isAccepted && (
        <button
          className="btn btn-primary rec-accept-btn"
          id="btn-accept-route"
          onClick={() => onAccept(option)}
        >
          ✓ Accept This Route & View Map
        </button>
      )}
      {isAccepted && (
        <div className="rec-accepted-tag">📍 Active on map</div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Panel
// ─────────────────────────────────────────────────────────────────────────────
const LOAD_STAGES = [
  'Fetching live corridor risk scores…',
  'Retrieving EIA Brent crude price…',
  'Computing route fuel & operational costs…',
  'Calculating war-risk insurance premiums…',
  'Scoring + ranking candidate routes…',
  'Generating AI decision walkthrough…',
];

export default function RoutingAdvisorPanel() {
  const [step, setStep] = useState('input');          // 'input' | 'loading' | 'results' | 'map'
  const [origin, setOrigin]           = useState('');
  const [destination, setDestination] = useState('');
  const [brentPrice, setBrentPrice]   = useState(null);
  const [result, setResult]           = useState(null);
  const [error, setError]             = useState(null);
  const [accepted, setAccepted]       = useState(null);  // accepted route option
  const [loadStage, setLoadStage]     = useState(0);
  const [showAllRoutes, setShowAllRoutes] = useState(false);
  const loadRef = useRef(null);

  // Load live Brent price for display in input form
  useEffect(() => {
    fetchCrudeOil()
      .then(d => setBrentPrice(d?.brent_usd))
      .catch(() => {});
  }, []);

  // Simulate stage-by-stage loading progress
  const runLoadStages = useCallback(() => {
    setLoadStage(0);
    let i = 0;
    const tick = () => {
      i += 1;
      setLoadStage(i);
      if (i < LOAD_STAGES.length) {
        loadRef.current = setTimeout(tick, 600 + Math.random() * 400);
      }
    };
    loadRef.current = setTimeout(tick, 700);
  }, []);

  useEffect(() => () => clearTimeout(loadRef.current), []);

  async function handleAnalyze() {
    if (!origin || !destination) return;
    setStep('loading');
    setError(null);
    setResult(null);
    setAccepted(null);
    runLoadStages();

    try {
      const data = await assessRoute(origin, destination);
      setResult(data);
      setStep('results');
    } catch (err) {
      setError(err?.response?.data?.detail ?? err?.message ?? 'Route analysis failed');
      setStep('input');
    }
  }

  function handleAccept(option) {
    setAccepted(option);
    setStep('map');
  }

  function handleRecalculate() {
    setStep('input');
    setResult(null);
    setAccepted(null);
    setShowAllRoutes(false);
  }

  // ── Map center based on route midpoint ──────────────────────────────────
  const mapCenter = (() => {
    if (!accepted?.waypoints?.length) return [20, 50];
    const lats = accepted.waypoints.map(w => w[0]);
    const lngs = accepted.waypoints.map(w => w[1]);
    return [
      (Math.min(...lats) + Math.max(...lats)) / 2,
      (Math.min(...lngs) + Math.max(...lngs)) / 2,
    ];
  })();

  // ── STEP 1: Input Form ──────────────────────────────────────────────────
  if (step === 'input') {
    return (
      <div className="route-advisor">
        <div className="route-advisor__hero">
          <div className="route-advisor__hero-title">
            🌍 Route Intelligence Advisor
          </div>
          <div className="route-advisor__hero-sub">
            AI-powered maritime route analysis combining live geopolitical risk scores,
            EIA crude oil prices, and war-risk insurance modeling.
          </div>
        </div>

        <div className="card route-form-card">
          <div className="card-header">
            <span className="card-title">📍 Configure Voyage</span>
            {brentPrice && (
              <span className="brent-badge">
                🛢️ Brent: <strong>${brentPrice?.toFixed(2)}/bbl</strong>
              </span>
            )}
          </div>
          <div className="card-body">
            <div className="route-form__ports">
              <PortSelect
                label="Origin Port"
                value={origin}
                onChange={setOrigin}
                exclude={destination}
              />
              <div className="route-form__arrow">→</div>
              <PortSelect
                label="Destination Port"
                value={destination}
                onChange={setDestination}
                exclude={origin}
              />
            </div>

            {error && (
              <div className="state-box" style={{ background: '#fef2f2', borderColor: '#fca5a5', color: '#dc2626', marginTop: 16 }}>
                <strong>⚠ {error}</strong>
              </div>
            )}

            <div className="route-form__footer">
              <div className="route-form__info">
                <span>🚢 Analysis includes: 1M barrel VLCC cargo</span>
                <span>·</span>
                <span>📊 Live corridor risk × EIA Brent price</span>
                <span>·</span>
                <span>🤖 Gemini AI decision walkthrough</span>
              </div>
              <button
                className="btn btn-primary route-analyze-btn"
                id="btn-analyze-route"
                onClick={handleAnalyze}
                disabled={!origin || !destination}
              >
                ⚡ Analyze Routes
              </button>
            </div>
          </div>
        </div>

        {/* Quick-select example voyages */}
        <div className="quick-routes">
          <div className="quick-routes__label">Quick select:</div>
          {[
            { o: 'ras_tanura', d: 'rotterdam',  label: 'Ras Tanura → Rotterdam' },
            { o: 'basrah',     d: 'chennai',    label: 'Basrah → Chennai' },
            { o: 'yanbu',      d: 'rotterdam',  label: 'Yanbu → Rotterdam' },
            { o: 'houston',    d: 'vadinar',    label: 'Houston → Vadinar' },
          ].map(ex => (
            <button
              key={ex.label}
              className="quick-route-btn"
              onClick={() => { setOrigin(ex.o); setDestination(ex.d); }}
            >
              {ex.label}
            </button>
          ))}
        </div>
      </div>
    );
  }

  // ── STEP 2: Loading ─────────────────────────────────────────────────────
  if (step === 'loading') {
    return (
      <div className="route-advisor">
        <div className="card route-loading-card">
          <div className="route-loading__title">
            <span className="spinner" style={{ width: 20, height: 20, borderWidth: 3, borderTopColor: 'var(--olive)' }} />
            Analyzing Routes…
          </div>
          <div className="route-loading__sub">
            {PORTS.find(p => p.id === origin)?.name} → {PORTS.find(p => p.id === destination)?.name}
          </div>
          <div className="route-loading__stages">
            {LOAD_STAGES.map((label, i) => (
              <LoadingStage key={label} label={label} done={loadStage > i} />
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ── STEP 3: Recommendation Results ─────────────────────────────────────
  if (step === 'results' && result) {
    const topOption    = result.options[0];
    const otherOptions = result.options.slice(1);
    const originPort   = PORTS.find(p => p.id === origin);
    const destPort     = PORTS.find(p => p.id === destination);

    return (
      <div className="route-advisor">
        {/* Journey header */}
        <div className="journey-header">
          <button className="btn-ghost" onClick={handleRecalculate}>← Recalculate</button>
          <div className="journey-route">
            <span>{originPort?.flag} {originPort?.name}</span>
            <span className="journey-arrow">✈ → 🚢</span>
            <span>{destPort?.flag} {destPort?.name}</span>
          </div>
          <span className="brent-badge">
            🛢️ ${result.brent_crude_usd?.toFixed(2)}/bbl
          </span>
        </div>

        <div className="results-layout">
          <div className="results-main">
            {/* Top recommendation */}
            <div className="results-section-label">🏆 Primary Recommendation</div>
            <RecommendationCard
              option={topOption}
              rank={0}
              onAccept={handleAccept}
              isAccepted={false}
            />

            {/* AI Rationale */}
            {result.decision_rationale_markdown && (
              <RationalePanel markdown={result.decision_rationale_markdown} />
            )}

            {/* Alternative routes */}
            {otherOptions.length > 0 && (
              <div>
                <button
                  className="context-toggle show-alts"
                  onClick={() => setShowAllRoutes(s => !s)}
                >
                  {showAllRoutes ? '▲ Hide alternatives' : `▼ Show ${otherOptions.length} alternative route(s)`}
                </button>
                {showAllRoutes && otherOptions.map((opt, i) => (
                  <RecommendationCard
                    key={opt.id}
                    option={opt}
                    rank={i + 1}
                    onAccept={handleAccept}
                    isAccepted={false}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Risk summary sidebar */}
          <div className="results-sidebar">
            <div className="card risk-summary-card">
              <div className="card-header">
                <span className="card-title">🌐 Corridor Risks</span>
              </div>
              <div className="card-body">
                {result.corridor_zones?.map(z => (
                  <div key={z.id} className="corridor-risk-row">
                    <div className="corridor-risk-label">{z.label}</div>
                    <div
                      className="corridor-risk-bar-wrap"
                      title={z.situation}
                    >
                      <div
                        className="corridor-risk-bar"
                        style={{
                          width: `${(z.risk || 0) * 100}%`,
                          background: riskColor(z.risk),
                        }}
                      />
                    </div>
                    <div
                      className="corridor-risk-score"
                      style={{ color: riskColor(z.risk) }}
                    >
                      {z.risk?.toFixed(3)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── STEP 4: Accepted Map View ───────────────────────────────────────────
  if (step === 'map' && accepted && result) {
    const originPort = PORTS.find(p => p.id === origin);
    const destPort   = PORTS.find(p => p.id === destination);

    return (
      <div className="route-advisor route-advisor--map">
        {/* Top control bar */}
        <div className="map-control-bar">
          <button className="btn-ghost" onClick={() => setStep('results')}>← Back to recommendations</button>
          <div className="journey-route">
            <span>{originPort?.flag} {result.origin.name}</span>
            <span className="journey-arrow">→</span>
            <span>{destPort?.flag} {result.destination.name}</span>
          </div>
          <button className="btn-ghost" onClick={handleRecalculate}>🔄 New voyage</button>
        </div>

        <div className="map-layout">
          {/* Map */}
          <div className="map-main">
            <SVGWorldMap
              origin={result.origin}
              destination={result.destination}
              waypoints={accepted.waypoints}
              corridorRiskZones={result.corridor_zones}
              activeOptionId={accepted.id}
            />
          </div>

          {/* Side panel */}
          <div className="map-sidebar">
            {/* Accepted route badge */}
            <div className="card accepted-route-card">
              <div className="accepted-route-header">
                <span className={`rec-badge ${recBadge(accepted.recommendation).cls}`}>
                  {recBadge(accepted.recommendation).label}
                </span>
              </div>
              <div className="accepted-route-name">{accepted.name}</div>
              <div className="rec-card__metrics" style={{ marginTop: 12 }}>
                <div className="rec-metric">
                  <div className="rec-metric__label">Distance</div>
                  <div className="rec-metric__value">{accepted.distance_nm?.toLocaleString()} NM</div>
                </div>
                <div className="rec-metric">
                  <div className="rec-metric__label">Transit</div>
                  <div className="rec-metric__value">{accepted.days} days</div>
                </div>
                <div className="rec-metric">
                  <div className="rec-metric__label">Risk</div>
                  <div className="rec-metric__value" style={{ color: riskColor(accepted.risk_score) }}>
                    {accepted.risk_score?.toFixed(3)}
                  </div>
                </div>
                <div className="rec-metric">
                  <div className="rec-metric__label">Total Cost</div>
                  <div className="rec-metric__value">{fmtCost(accepted.total_cost_usd)}</div>
                </div>
              </div>
            </div>

            {/* Cost chart */}
            <div className="card" style={{ marginTop: 12 }}>
              <CostBreakdownChart option={accepted} />
            </div>

            {/* AI walkthrough */}
            {result.decision_rationale_markdown && (
              <div className="card" style={{ marginTop: 12 }}>
                <RationalePanel markdown={result.decision_rationale_markdown} />
              </div>
            )}

            {/* Map legend */}
            <div className="card map-legend-card">
              <div className="map-legend-title">Map Legend</div>
              <div className="map-legend-item">
                <div className="map-legend-line" style={{ background: '#22d3ee' }} />
                <span>Accepted route (animated)</span>
              </div>
              <div className="map-legend-item">
                <div className="map-legend-line" style={{ background: '#6b7280', border: '1px dashed #6b7280' }} />
                <span>Alternative routes</span>
              </div>
              <div className="map-legend-item">
                <div style={{ width: 16, height: 16, borderRadius: '50%', background: '#ef4444', opacity: 0.3, border: '1px dashed #ef4444' }} />
                <span>High-risk zones</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return null;
}
