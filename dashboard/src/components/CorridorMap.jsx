/**
 * CorridorMap.jsx
 *
 * High-performance SVG Vector Map replacement for the main dashboard.
 * Renders major global shipping corridors with live risk highlights,
 * supporting instant click/hover responses to select corridors.
 */
import { useState, useEffect } from 'react';
import { fetchRiskScores } from '../api';
import SVGWorldMap from './SVGWorldMap';

export default function CorridorMap({ onSelectCorridor }) {
  const [scores, setScores] = useState([]);
  const [error, setError]   = useState(null);

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchRiskScores();
        setScores(data);
      } catch (e) {
        setError('Could not load risk scores');
      }
    }
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, []);

  // Map backend corridors to SVG coordinate zones
  const corridorZones = [
    {
      id: 'hormuz',
      label: 'Strait of Hormuz',
      coords: [26.5, 56.3],
      radius_km: 120,
      risk: scores.find(s => s.corridor === 'hormuz')?.risk_score ?? 0.35,
      situation: scores.find(s => s.corridor === 'hormuz')?.explanation ?? 'Persian Gulf transit operations.'
    },
    {
      id: 'red_sea',
      label: 'Bab-el-Mandeb / Red Sea',
      coords: [12.6, 43.4],
      radius_km: 200,
      risk: scores.find(s => s.corridor === 'red_sea')?.risk_score ?? 0.55,
      situation: scores.find(s => s.corridor === 'red_sea')?.explanation ?? 'Red Sea security operations.'
    }
  ];

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', minHeight: 430 }}>
      <div className="card-header">
        <span className="card-title">Corridor Map — Live Vector View</span>
        {error && <span style={{ fontSize: 11, color: 'var(--risk-high)' }}>{error}</span>}
      </div>
      <div className="map-wrap" style={{ flex: 1, padding: 8 }}>
        <SVGWorldMap
          corridorRiskZones={corridorZones}
          onSelectCorridor={onSelectCorridor}
        />
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 14, padding: '10px 16px', borderTop: '1px solid var(--border)', flexWrap: 'wrap' }}>
        {[
          { cls: 'low',  label: 'Low (<0.35)' },
          { cls: 'mid',  label: 'Medium (0.35–0.65)' },
          { cls: 'high', label: 'High (>0.65)' },
        ].map(({ cls, label }) => (
          <span key={cls} className={`risk-badge ${cls}`} style={{ fontSize: 10 }}>
            <span className="risk-dot" />{label}
          </span>
        ))}
        <span style={{ fontSize: 10, color: 'var(--text-3)', marginLeft: 'auto', alignSelf: 'center' }}>
          Interactive pulse rings indicate risk corridors
        </span>
      </div>
    </div>
  );
}
