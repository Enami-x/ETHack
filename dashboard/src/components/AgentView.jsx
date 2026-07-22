/**
 * AgentView.jsx — n8n-style live workflow visualization
 *
 * Shows a 6-node pipeline graph with animated connectors.
 * Connects to the SSE stream at /api/pipeline/stream for real-time updates.
 * Falls back to polling when SSE is not connected.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { triggerPipeline, fetchPipelineStatus, createPipelineStream } from '../api';

// ── Stage metadata ─────────────────────────────────────────────────────────
const STAGES = [
  {
    id: 'stage_1',
    label: 'Data Collection',
    sub: 'OFAC · RSS Feeds',
    icon: '📡',
  },
  {
    id: 'stage_2',
    label: 'Normalization',
    sub: 'Signal Processing',
    icon: '⚙️',
  },
  {
    id: 'stage_3',
    label: 'Risk Intelligence',
    sub: 'Gemini LLM Scoring',
    icon: '🧠',
  },
  {
    id: 'stage_4',
    label: 'Scenario Modeling',
    sub: 'Parametric Analysis',
    icon: '📊',
  },
  {
    id: 'stage_5',
    label: 'Procurement',
    sub: 'Supplier Ranking',
    icon: '🛒',
  },
  {
    id: 'stage_6',
    label: 'Reserve Optimizer',
    sub: 'SPR Drawdown',
    icon: '🛢️',
  },
];

// ── Initial node state factory ─────────────────────────────────────────────
function freshNodeState() {
  const obj = {};
  STAGES.forEach(s => {
    obj[s.id] = { status: 'idle', elapsed: null, data: {} };
  });
  return obj;
}

// ── Timestamp formatter ────────────────────────────────────────────────────
function fmtTs(isoStr) {
  try {
    return new Date(isoStr).toLocaleTimeString('en-US', { hour12: false });
  } catch {
    return '—';
  }
}

// ── Single agent node card ─────────────────────────────────────────────────
function AgentNode({ stage, state, maxElapsed }) {
  const { status, elapsed, data } = state;

  // Timing bar width as a % of max elapsed (gives relative visual weight)
  const barWidth =
    status === 'done' && elapsed != null && maxElapsed > 0
      ? Math.max(6, Math.round((elapsed / maxElapsed) * 100))
      : 0;

  return (
    <div className={`agent-node ${status}`}>
      <div className="agent-node-card">
        <div className="node-dot" />
        <div className="agent-node-icon">{stage.icon}</div>
        <div>
          <div className="agent-node-name">{stage.label}</div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>
            {stage.sub}
          </div>
        </div>
        <div className="agent-node-status">
          {status === 'idle'    && 'Waiting'}
          {status === 'running' && 'Running…'}
          {status === 'done'    && 'Complete'}
          {status === 'error'   && 'Error'}
        </div>
        {elapsed != null && status === 'done' && (
          <div className="agent-node-elapsed">{elapsed}s</div>
        )}
        {status === 'done' && data && Object.keys(data).length > 0 && (
          <div style={{
            fontSize: 10,
            color: 'var(--text-3)',
            borderTop: '1px solid var(--border)',
            paddingTop: 6,
            width: '100%',
            textAlign: 'left',
            lineHeight: 1.6,
          }}>
            {Object.entries(data).map(([k, v]) =>
              k !== 'elapsed' && v !== undefined ? (
                <div key={k}>
                  <span style={{ color: 'var(--text-3)' }}>{k.replace(/_/g, ' ')}:</span>{' '}
                  <span style={{ color: 'var(--brown)', fontWeight: 600 }}>{String(v)}</span>
                </div>
              ) : null
            )}
          </div>
        )}
      </div>

      {/* Timing bar */}
      <div className="agent-node-timing">
        <div
          className="agent-node-timing-fill"
          style={{ width: `${barWidth}%` }}
        />
      </div>
    </div>
  );
}

// ── Connector between two nodes ────────────────────────────────────────────
function Connector({ leftStatus, rightStatus }) {
  // Light up connector once the left node is done
  const cls =
    leftStatus === 'done' || rightStatus === 'running' || rightStatus === 'done'
      ? leftStatus === 'done'
        ? 'done'
        : 'active'
      : rightStatus === 'running'
      ? 'active'
      : '';

  return (
    <div className="workflow-connector">
      <div className={`connector-line ${cls}`} />
      <div className="connector-arrow" />
    </div>
  );
}

// ── Log entry ──────────────────────────────────────────────────────────────
function LogLine({ entry }) {
  const msgClass =
    entry.type === 'stage_start'
      ? 'start'
      : entry.type === 'stage_done'
      ? 'done'
      : entry.type === 'stage_error'
      ? 'error'
      : entry.type === 'pipeline_start' || entry.type === 'pipeline_done'
      ? 'pipeline'
      : '';

  return (
    <div className="log-line">
      <span className="log-ts">{fmtTs(entry.ts)}</span>
      <span className={`log-msg ${msgClass}`}>{entry.message}</span>
    </div>
  );
}

// ── Pipeline summary stats ─────────────────────────────────────────────────
function PipelineSummary({ nodes, totalElapsed, running }) {
  const doneCount = STAGES.filter(s => nodes[s.id].status === 'done').length;
  const errorCount = STAGES.filter(s => nodes[s.id].status === 'error').length;

  return (
    <div className="pipeline-summary">
      <div className="pipeline-summary-item">
        <div className="pipeline-summary-label">Status</div>
        <div className="pipeline-summary-value" style={{
          color: running ? 'var(--gold)' : errorCount > 0 ? 'var(--amber)' : doneCount === STAGES.length ? 'var(--olive)' : 'var(--text-3)'
        }}>
          {running ? '⚡ Running' : doneCount === STAGES.length ? '✓ Complete' : errorCount > 0 ? '⚠ Errors' : '— Idle'}
        </div>
      </div>

      <div className="pipeline-summary-item">
        <div className="pipeline-summary-label">Stages Done</div>
        <div className="pipeline-summary-value">{doneCount} / {STAGES.length}</div>
      </div>

      <div className="pipeline-summary-item">
        <div className="pipeline-summary-label">Total Elapsed</div>
        <div className="pipeline-summary-value">
          {totalElapsed != null ? `${totalElapsed}s` : running ? '…' : '—'}
        </div>
      </div>

      <div className="pipeline-summary-item">
        <div className="pipeline-summary-label">Errors</div>
        <div className="pipeline-summary-value" style={{ color: errorCount > 0 ? 'var(--amber)' : 'var(--text-3)' }}>
          {errorCount}
        </div>
      </div>
    </div>
  );
}

// ── Progress dots ──────────────────────────────────────────────────────────
function ProgressDots({ nodes }) {
  return (
    <div className="stage-progress-row">
      {STAGES.map(s => (
        <div key={s.id} className={`progress-dot ${nodes[s.id].status}`} title={s.label} />
      ))}
    </div>
  );
}

// ── Main AgentView ─────────────────────────────────────────────────────────
export default function AgentView({ externalRunning, externalResult }) {
  const [nodes, setNodes]           = useState(freshNodeState);
  const [logs, setLogs]             = useState([]);
  const [running, setRunning]       = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [elapsed, setElapsed]       = useState(0);
  const [totalElapsed, setTotalElapsed] = useState(null);
  const [sseConnected, setSseConnected] = useState(false);
  const [error, setError]           = useState(null);
  const [mode, setMode]             = useState(null); // 'live' | 'simulate'

  const eventSourceRef = useRef(null);
  const timerRef       = useRef(null);
  const logEndRef      = useRef(null);

  // ── Auto-scroll log ──────────────────────────────────────────────────────
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  // ── Append log helper ────────────────────────────────────────────────────
  const addLog = useCallback((type, message, ts) => {
    setLogs(prev => [
      ...prev,
      { type, message, ts: ts || new Date().toISOString() }
    ]);
  }, []);

  // ── Handle incoming SSE event ────────────────────────────────────────────
  const handleEvent = useCallback((event) => {
    const { type, stage, label, ts, data } = event;

    if (type === 'heartbeat') return;

    if (type === 'pipeline_start') {
      setNodes(freshNodeState());
      setTotalElapsed(null);
      addLog('pipeline_start', '▶  Pipeline started', ts);
      return;
    }

    if (type === 'pipeline_done') {
      const latency = data?.total_latency_seconds;
      setTotalElapsed(latency != null ? Math.round(latency) : null);
      setRunning(false);
      clearInterval(timerRef.current);
      addLog('pipeline_done', `✓  Pipeline complete in ${latency?.toFixed(1) ?? '?'}s`, ts);
      return;
    }

    if (type === 'stage_start') {
      setNodes(prev => ({
        ...prev,
        [stage]: { ...prev[stage], status: 'running', elapsed: null, data: {} },
      }));
      addLog('stage_start', `▷  [${label ?? stage}] started`, ts);
      return;
    }

    if (type === 'stage_done') {
      setNodes(prev => ({
        ...prev,
        [stage]: {
          status: 'done',
          elapsed: data?.elapsed ?? null,
          data: { ...data },
        },
      }));
      addLog('stage_done', `✓  [${label ?? stage}] done in ${data?.elapsed ?? '?'}s`, ts);
      return;
    }

    if (type === 'stage_error') {
      setNodes(prev => ({
        ...prev,
        [stage]: { ...prev[stage], status: 'error', data: { error: data?.error } },
      }));
      addLog('stage_error', `⚠  [${label ?? stage}] error: ${data?.error ?? ''}`, ts);
      return;
    }
  }, [addLog]);

  // ── Connect SSE ──────────────────────────────────────────────────────────
  useEffect(() => {
    let es;
    try {
      es = createPipelineStream();
      eventSourceRef.current = es;

      es.onopen = () => setSseConnected(true);

      es.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data);
          handleEvent(event);
        } catch { /* ignore parse errors */ }
      };

      es.onerror = () => {
        setSseConnected(false);
        // EventSource auto-reconnects — no action needed
      };
    } catch {
      setSseConnected(false);
    }

    return () => {
      es?.close();
      setSseConnected(false);
    };
  }, [handleEvent]);

  // ── Auto-load last pipeline state on mount ───────────────────────────────
  useEffect(() => {
    async function loadLastRun() {
      try {
        const status = await fetchPipelineStatus();
        if (!status || status.status === 'no_runs_yet' || !status.stage_timings) return;
        const fb = {};
        STAGES.forEach(s => {
          const timing = status.stage_timings?.[s.id];
          fb[s.id] = { status: timing != null ? 'done' : 'idle', elapsed: timing != null ? Math.round(timing) : null, data: {} };
        });
        setNodes(fb);
        if (status.total_latency_seconds) setTotalElapsed(Math.round(status.total_latency_seconds));
        addLog('pipeline_done', `↩  Last run restored · ${status.total_latency_seconds?.toFixed(1) ?? '?'}s total`);
      } catch { /* no previous run available */ }
    }
    loadLastRun();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Elapsed counter while running ────────────────────────────────────────
  useEffect(() => {
    if (running) {
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed(e => e + 1), 1000);
    } else {
      clearInterval(timerRef.current);
    }
    return () => clearInterval(timerRef.current);
  }, [running]);

  // ── Trigger pipeline ─────────────────────────────────────────────────────
  async function handleRun() {
    if (running || simulating) return;
    setRunning(true);
    setMode('live');
    setError(null);
    setNodes(freshNodeState());
    setLogs([]);
    setTotalElapsed(null);
    addLog('pipeline_start', '▶  Triggering live pipeline…');

    try {
      const result = await triggerPipeline();
      if (!sseConnected) {
        setTotalElapsed(Math.round(result?.total_latency_seconds ?? 0));
        addLog('pipeline_done', `✓  Pipeline complete in ${result?.total_latency_seconds?.toFixed(1) ?? '?'}s`);
        const fb = {};
        STAGES.forEach(s => {
          const timing = result?.stage_timings?.[s.id];
          fb[s.id] = { status: 'done', elapsed: timing ? Math.round(timing) : null, data: {} };
        });
        setNodes(fb);
      }
    } catch (err) {
      const msg = err?.response?.data?.detail ?? err?.message ?? 'Unknown error';
      setError(`Pipeline failed: ${msg}`);
      addLog('stage_error', `⚠  ${msg}`);
    } finally {
      setRunning(false);
      clearInterval(timerRef.current);
    }
  }

  // ── Geopolitical Crisis Scenario Simulation ────────────────────────────────
  const CRISIS_STAGES = [
    {
      stageId: 'stage_1', label: 'Data Collection', duration: 900,
      logs: [
        'OFAC SDN scan: 1,088 Iranian vessel/petroleum entities flagged',
        'RSS GCaptain: IRGC speedboat intercepts — 4 incidents in 48h',
        'EIA BRENT: $94.2/bbl — +15.7% 7-day surge detected',
        'AIS anomaly: 23 VLCC tankers holding at Fujairah anchorage',
      ],
      data: { signals_collected: 1109, eia_brent: 94.2, eia_source: 'eia_live' },
    },
    {
      stageId: 'stage_2', label: 'Signal Normalization', duration: 600,
      logs: [
        '1,109 raw signals → 28 processed (OFAC + 14 news + 2 price)',
        'OFAC aggregate: corridor=hormuz, severity_hint=0.85 (CRITICAL)',
        'EIA price signal severity: 0.978 — extreme 7-day volatility',
      ],
      data: { processed: 28 },
    },
    {
      stageId: 'stage_3', label: 'Risk Intelligence', duration: 1800,
      logs: [
        '🧠 HORMUZ: acute_score=0.94 (news×0.75=0.92, price×0.25=0.89)',
        '🧠 HORMUZ: sanctions_floor=0.40 → final risk_score=0.94 (acute-driven)',
        '🧠 RED_SEA: risk_score=0.81 — Houthi drone activity + Brent spike',
        'Confidence: 0.97 — 5 corroborating types, all <24h recency',
        'LLM: "IRGC fast-attack craft in northern Hormuz choke. US 5th Fleet DEFCON-3."',
      ],
      data: { corridors_scored: 2, hormuz_risk: '0.940', red_sea_risk: '0.810' },
    },
    {
      stageId: 'stage_4', label: 'Scenario Modeling', duration: 700,
      logs: [
        'HORMUZ_PARTIAL_CLOSURE @ sev=0.94: global supply_gap=+21%',
        'Brent price impact: +$18.4/bbl (90-day, elasticity=0.62)',
        'Refinery utilization drop: Vadinar −14.2%, Rotterdam −9.1%',
        'SPR days-of-cover at current consumption: 8.3 days',
      ],
      data: { scenarios_run: 3, supply_gap_pct: '21.0%', price_impact_pct: '+22.5%' },
    },
    {
      stageId: 'stage_5', label: 'Procurement Ranking', duration: 500,
      logs: [
        '#1 USA WTI (Houston) — score=0.91, 18d transit, $92.8/bbl, 0 chokepoints',
        '#2 Guyana Stabroek — score=0.84, 22d, $91.1/bbl, Cape route',
        '#3 Nigeria Bonny Light — score=0.78, ECOWAS corridor, risk=0.12',
        '❌ Saudi Ras Tanura BLOCKED — Hormuz dependency risk=0.94',
      ],
      data: { recs_generated: 5, top_supplier: 'USA WTI (Houston)' },
    },
    {
      stageId: 'stage_6', label: 'Reserve Optimization', duration: 400,
      logs: [
        'SPR baseline: 347M barrels · draw capacity: 726,169 kb/day',
        'Drawdown schedule: 1.2M bbl/day × 18 days to bridge supply gap',
        'Replenishment window: 45 days post-disruption (lead time buffer)',
        '📋 ACTION: Activate IEA coordinated emergency SPR release',
      ],
      data: { days_cover: '8.3', drawdown_rate: '1.2M bbl/day' },
    },
  ];

  async function handleSimulate() {
    if (running || simulating) return;
    setSimulating(true);
    setMode('simulate');
    setError(null);
    setNodes(freshNodeState());
    setLogs([]);
    setTotalElapsed(null);

    addLog('pipeline_start', '▶  CRISIS SCENARIO: Strait of Hormuz — Partial Closure');
    addLog('pipeline_start', '────────────────────────────────────────────────────────');

    let totalMs = 0;
    for (const stage of CRISIS_STAGES) {
      setNodes(prev => ({ ...prev, [stage.stageId]: { status: 'running', elapsed: null, data: {} } }));
      addLog('stage_start', `▷  [${stage.label}] running…`, new Date().toISOString());

      const msPerLog = Math.floor(stage.duration / (stage.logs.length + 1));
      for (const log of stage.logs) {
        await new Promise(r => setTimeout(r, msPerLog));
        addLog('stage_start', `   ${log}`, new Date().toISOString());
      }
      await new Promise(r => setTimeout(r, msPerLog));

      const elapsedSec = +(stage.duration / 1000).toFixed(2);
      totalMs += stage.duration;
      setNodes(prev => ({ ...prev, [stage.stageId]: { status: 'done', elapsed: elapsedSec, data: stage.data } }));
      addLog('stage_done', `✓  [${stage.label}] complete in ${elapsedSec}s`, new Date().toISOString());
    }

    const totalSec = +(totalMs / 1000).toFixed(1);
    setTotalElapsed(totalSec);
    addLog('pipeline_done', '────────────────────────────────────────────────────────');
    addLog('pipeline_done', `✓  CRISIS SIMULATION COMPLETE — ${totalSec}s`);
    addLog('pipeline_done', '⚡  ACTION: Activate SPR emergency drawdown · Reroute via USA WTI');
    setSimulating(false);
  }


  // ── Max elapsed (for timing bar normalisation) ───────────────────────────
  const maxElapsed = Math.max(
    1,
    ...STAGES.map(s => nodes[s.id].elapsed ?? 0)
  );

  return (
    <div className="agent-view">

      {/* ── Header row ─────────────────────────────────────────────────── */}
      <div className="agent-run-header">
        <div>
          <div className="agent-run-title">Agent Workflow</div>
          <div className="agent-run-sub">
            Live execution view · 6 pipeline stages
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          {/* SSE indicator */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: sseConnected ? 'var(--olive)' : 'var(--text-3)' }}>
            <span style={{
              width: 7, height: 7, borderRadius: '50%',
              background: sseConnected ? 'var(--olive)' : 'var(--border)',
              display: 'inline-block',
              ...(sseConnected ? { animation: 'dot-blink 2s ease-in-out infinite' } : {}),
            }} />
            {sseConnected ? 'Live stream connected' : 'Connecting…'}
          </div>

          {mode && (
            <span style={{
              fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
              background: mode === 'simulate' ? 'rgba(171,194,112,.15)' : 'rgba(70,60,51,.08)',
              color: mode === 'simulate' ? 'var(--olive)' : 'var(--brown)',
              textTransform: 'uppercase', letterSpacing: '.05em',
            }}>
              {mode === 'simulate' ? '⚡ Simulator' : '🔴 Live'}
            </span>
          )}

          {error && (
            <span style={{ fontSize: 11, color: 'var(--amber)' }}>{error}</span>
          )}

          <button
            className="btn btn-primary"
            onClick={handleRun}
            disabled={running || simulating}
            title="Run the full live pipeline (OFAC + RSS + EIA + LLM)"
          >
            {running ? (
              <>
                <span className="spinner" />
                Running… {elapsed}s
              </>
            ) : (
              '▶ Run Live'
            )}
          </button>

          <button
            className="btn btn-olive"
            onClick={handleSimulate}
            disabled={running || simulating}
            title="Simulate a Hormuz closure crisis — scripted geopolitical scenario with specific intelligence"
          >
            {simulating ? (
              <>
                <span className="spinner" />
                Simulating crisis…
              </>
            ) : (
              '⚡ Simulate Crisis'
            )}
          </button>
        </div>
      </div>

      {/* ── Summary bar ────────────────────────────────────────────────── */}
      <PipelineSummary nodes={nodes} totalElapsed={totalElapsed} running={running} />

      {/* ── Workflow canvas ─────────────────────────────────────────────── */}
      <div className="workflow-canvas">
        <div className="workflow-nodes">
          {STAGES.map((stage, idx) => (
            <div key={stage.id} style={{ display: 'flex', alignItems: 'center' }}>
              <AgentNode
                stage={stage}
                state={nodes[stage.id]}
                maxElapsed={maxElapsed}
              />
              {idx < STAGES.length - 1 && (
                <Connector
                  leftStatus={nodes[STAGES[idx].id].status}
                  rightStatus={nodes[STAGES[idx + 1].id].status}
                />
              )}
            </div>
          ))}
        </div>

        <ProgressDots nodes={nodes} />
      </div>

      {/* ── Live log terminal ───────────────────────────────────────────── */}
      <div>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 8
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-2)', letterSpacing: '.05em', textTransform: 'uppercase' }}>
            Live Log
          </div>
          {logs.length > 0 && (
            <button
              style={{ fontSize: 11, background: 'none', border: 'none', color: 'var(--text-3)', cursor: 'pointer' }}
              onClick={() => setLogs([])}
            >
              Clear
            </button>
          )}
        </div>
        <div className="agent-log">
          {logs.length === 0 ? (
            <div style={{ color: '#6B6058', fontStyle: 'italic' }}>
              Waiting for pipeline to start…
            </div>
          ) : (
            logs.map((entry, i) => <LogLine key={i} entry={entry} />)
          )}
          <div ref={logEndRef} />
        </div>
      </div>
    </div>
  );
}
