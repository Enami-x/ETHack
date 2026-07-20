/**
 * RiskExplanationPanel.jsx
 * Displays the full Gemini-generated explanation for whichever corridor
 * is currently selected/hovered on the map. Receives corridorId + riskScores
 * as props (state managed by App.jsx).
 */
const CORRIDOR_LABELS = {
  hormuz:  'Strait of Hormuz',
  red_sea: 'Bab-el-Mandeb / Red Sea',
  suez:    'Suez Canal',
  other:   'Other',
};

export default function RiskExplanationPanel({ corridorId, riskScores = [] }) {
  const row   = riskScores.find(r => r.corridor === corridorId);
  const label = CORRIDOR_LABELS[corridorId] ?? corridorId;

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">
          Risk Explanation
          {corridorId && <span style={{ color: 'var(--text-2)', fontWeight: 400, marginLeft: 8 }}>— {label}</span>}
        </span>
        {row?.generated_at && (
          <span className="last-updated">
            Generated {new Date(row.generated_at).toLocaleString()}
          </span>
        )}
      </div>
      <div className="card-body">
        {!corridorId && (
          <p className="explanation-empty">
            Click or hover a marker on the map to view its AI-generated risk explanation.
          </p>
        )}

        {corridorId && !row && (
          <p className="explanation-empty">
            No explanation available for this corridor yet — run the pipeline to generate one.
          </p>
        )}

        {row?.explanation && (
          <p className="explanation-text">{row.explanation}</p>
        )}

        {row && !row.explanation && (
          <p className="explanation-empty">Explanation field is empty on this record.</p>
        )}

        {row?.contributing_signals?.length > 0 && (
          <div style={{ marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
            <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '.05em', color: 'var(--text-3)', marginBottom: 6 }}>
              Contributing signals ({row.contributing_signals.length})
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', wordBreak: 'break-all', lineHeight: 1.8 }}>
              {row.contributing_signals.join(' · ')}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
