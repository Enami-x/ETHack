/**
 * CorridorMap.jsx
 *
 * Live geopolitical corridor map powered by Leaflet.js.
 * Dark CartoDB tile layer with risk zone overlays and real route lines.
 */
import { useState, useEffect } from 'react';
import { fetchRiskScores } from '../api';
import LeafletRouteMap from './LeafletRouteMap';

export default function CorridorMap({ onSelectCorridor }) {
  const [scores, setScores] = useState([]);
  const [error, setError]   = useState(null);

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchRiskScores();
        setScores(data);
      } catch {
        setError('Could not load risk scores');
      }
    }
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, []);

  const corridorZones = [
    {
      id: 'hormuz',
      label: 'Strait of Hormuz',
      coords: [26.5, 56.3],
      radius_km: 180,
      risk: scores.find(s => s.corridor === 'hormuz')?.risk_score ?? 0.35,
      situation: scores.find(s => s.corridor === 'hormuz')?.explanation ?? 'Persian Gulf transit operations.',
    },
    {
      id: 'red_sea',
      label: 'Bab-el-Mandeb / Red Sea',
      coords: [12.6, 43.4],
      radius_km: 280,
      risk: scores.find(s => s.corridor === 'red_sea')?.risk_score ?? 0.55,
      situation: scores.find(s => s.corridor === 'red_sea')?.explanation ?? 'Red Sea security operations.',
    },
    {
      id: 'suez',
      label: 'Suez Canal',
      coords: [30.5, 32.5],
      radius_km: 120,
      risk: 0.25,
      situation: 'Suez Canal operational. Red Sea approach remains the primary risk vector.',
    },
  ];

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', minHeight: 460 }}>
      <div className="card-header">
        <span className="card-title">🗺 Live Corridor Map</span>
        {error && <span style={{ fontSize: 11, color: 'var(--risk-high)' }}>{error}</span>}
        <span style={{ fontSize: 10, color: 'var(--text-3)' }}>Click a zone to inspect risk</span>
      </div>
      <div style={{ flex: 1, padding: 10, minHeight: 400 }}>
        <LeafletRouteMap
          corridorRiskZones={corridorZones}
          onSelectCorridor={onSelectCorridor}
        />
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 14, padding: '10px 16px', borderTop: '1px solid var(--border)', flexWrap: 'wrap', alignItems: 'center' }}>
        {[
          { color: '#22c55e', label: 'Low (<0.35)' },
          { color: '#f59e0b', label: 'Medium (0.35–0.65)' },
          { color: '#ef4444', label: 'High (>0.65)' },
        ].map(({ color, label }) => (
          <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, color: 'var(--text-2)' }}>
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: color, display: 'inline-block' }} />
            {label}
          </span>
        ))}
        <span style={{ fontSize: 10, color: 'var(--text-3)', marginLeft: 'auto' }}>
          Zoom &amp; pan · hover zones for details
        </span>
      </div>
    </div>
  );
}
