/**
 * SVGWorldMap.jsx
 *
 * A high-performance, zero-latency Vector World Map for the ETHack dashboard.
 * Projects Latitude & Longitude coordinates onto a premium 1000x500 dark vector map.
 * Fully interactive with route animations, glowing corridor hotspots, and custom tooltips.
 */
import { useState, useRef, useEffect } from 'react';

// ─────────────────────────────────────────────────────────────────────────────
// Simplified global landmass path coordinates (Equirectangular projection)
// Hand-crafted polygon nodes mapping standard geography onto a 1000x500 canvas.
// ─────────────────────────────────────────────────────────────────────────────
const LANDMASSES = [
  // North America
  {
    name: 'North America',
    points: [
      [-168, 65], [-160, 70], [-120, 75], [-80, 80], [-60, 60], [-50, 45],
      [-80, 25], [-90, 15], [-95, 15], [-100, 20], [-110, 22], [-115, 30],
      [-125, 48], [-140, 60], [-160, 60]
    ]
  },
  // South America
  {
    name: 'South America',
    points: [
      [-80, 10], [-70, 12], [-50, -5], [-35, -5], [-40, -20], [-60, -45],
      [-75, -55], [-73, -40], [-70, -20], [-80, -5], [-81, 5]
    ]
  },
  // Greenland
  {
    name: 'Greenland',
    points: [
      [-60, 80], [-30, 80], [-20, 70], [-40, 60], [-50, 60]
    ]
  },
  // Africa
  {
    name: 'Africa',
    points: [
      [-17, 32], [-5, 36], [10, 36], [30, 31], [33, 28], [34, 12], [43, 11],
      [51, 10], [46, -10], [40, -25], [30, -34], [18, -34], [10, -10],
      [8, 4], [-10, 5], [-15, 15], [-17, 20]
    ]
  },
  // Eurasia
  {
    name: 'Eurasia',
    points: [
      [-10, 60], [10, 60], [30, 70], [60, 75], [90, 75], [120, 75], [140, 75],
      [170, 70], [180, 65], [170, 50], [140, 35], [130, 22], [115, 10], [108, 15],
      [100, 5], [95, 10], [90, 22], [78, 8], [72, 20], [60, 25], [48, 12],
      [44, 25], [38, 30], [27, 35], [15, 30], [5, 36], [-8, 36], [-9, 42],
      [-5, 50], [-10, 55]
    ]
  },
  // Great Britain / Ireland
  {
    name: 'British Isles',
    points: [
      [-10, 56], [-5, 58], [-2, 55], [-5, 50], [-10, 52]
    ]
  },
  // Australia
  {
    name: 'Australia',
    points: [
      [113, -25], [120, -15], [135, -12], [143, -10], [153, -28], [150, -38],
      [140, -38], [135, -35], [115, -34]
    ]
  },
  // India (Detailed sub-polygon for cargo visualization context)
  {
    name: 'India',
    points: [
      [68, 24], [72, 22], [73, 16], [78, 8], [80, 10], [82, 16], [88, 22],
      [80, 25], [72, 26]
    ]
  },
  // Madagascar
  {
    name: 'Madagascar',
    points: [
      [49, -12], [51, -16], [47, -25], [43, -25], [47, -15]
    ]
  },
  // Japan
  {
    name: 'Japan',
    points: [
      [130, 32], [135, 35], [142, 43], [140, 35]
    ]
  }
];

// Coordinate projection helper functions (Lat/Long → X/Y)
// Fits coordinates inside a 1000x500 SVG canvas coordinate system.
function projectLng(lng) {
  // map [-180, 180] to [0, 1000]
  // Shift center slightly to focus on shipping corridors (stretch/translate)
  return ((lng + 180) * 1000) / 360;
}

function projectLat(lat) {
  // map [90, -90] to [0, 500]
  return ((90 - lat) * 500) / 180;
}

export default function SVGWorldMap({
  origin,
  destination,
  waypoints = [],
  corridorRiskZones = [],
  activeOptionId = null,
  onSelectCorridor = null,
}) {
  const [tooltip, setTooltip] = useState(null);
  const mapRef = useRef(null);

  // Generate SVG path for a landmass polygon
  const makeLandPath = (points) => {
    if (!points || points.length === 0) return '';
    const d = points
      .map((p, idx) => `${idx === 0 ? 'M' : 'L'}${projectLng(p[0])} ${projectLat(p[1])}`)
      .join(' ');
    return d + ' Z';
  };

  // Generate path string for routes
  const makeRoutePath = (wps) => {
    if (!wps || wps.length < 2) return '';
    return wps
      .map((wp, idx) => `${idx === 0 ? 'M' : 'L'}${projectLng(wp[1])} ${projectLat(wp[0])}`) // Note: waypoints are [lat, lng]
      .join(' ');
  };

  const handleMouseMove = (e, content) => {
    if (!mapRef.current) return;
    const rect = mapRef.current.getBoundingClientRect();
    setTooltip({
      x: e.clientX - rect.left + 15,
      y: e.clientY - rect.top + 10,
      content,
    });
  };

  const handleMouseLeave = () => {
    setTooltip(null);
  };

  return (
    <div
      ref={mapRef}
      className="svg-map-container"
      style={{
        position: 'relative',
        background: '#090d16',
        border: '1.5px solid var(--border)',
        borderRadius: 12,
        overflow: 'hidden',
        width: '100%',
        height: '100%',
        minHeight: 480,
      }}
    >
      <svg
        viewBox="0 0 1000 500"
        style={{
          width: '100%',
          height: '100%',
          display: 'block',
        }}
      >
        {/* Ocean Graticules (Grid lines) */}
        <g stroke="rgba(255,255,255,0.02)" strokeWidth="0.5">
          {Array.from({ length: 9 }).map((_, i) => (
            <line key={`v-${i}`} x1={i * 100 + 100} y1={0} x2={i * 100 + 100} y2={500} />
          ))}
          {Array.from({ length: 4 }).map((_, i) => (
            <line key={`h-${i}`} x1={0} y1={i * 100 + 100} x2={1000} y2={i * 100 + 100} />
          ))}
        </g>

        {/* Global Landmasses */}
        <g className="svg-landmasses">
          {LANDMASSES.map((land) => (
            <path
              key={land.name}
              d={makeLandPath(land.points)}
              fill="#111827"
              stroke="#1f2937"
              strokeWidth="1.2"
              style={{ transition: 'fill 0.3s' }}
            />
          ))}
        </g>

        {/* Risk Corridor Zone Overlays (glowing circular highlights) */}
        {corridorRiskZones.map((zone) => {
          const cx = projectLng(zone.coords[1]);
          const cy = projectLat(zone.coords[0]);
          const riskVal = zone.risk || 0.25;
          let color = '#10b981'; // green
          if (riskVal > 0.65) color = '#ef4444'; // red
          else if (riskVal > 0.35) color = '#f59e0b'; // orange

          return (
            <g
              key={zone.id}
              className="svg-risk-zone"
              onClick={() => onSelectCorridor && onSelectCorridor(zone.id)}
              style={{ cursor: 'pointer' }}
            >
              {/* Outer pulsing ring */}
              <circle
                cx={cx}
                cy={cy}
                r={30 + riskVal * 25}
                fill={color}
                fillOpacity="0.04"
                stroke={color}
                strokeWidth="1"
                strokeOpacity="0.3"
                strokeDasharray="4 3"
                className="pulse-ring"
              />
              {/* Inner highlight circle */}
              <circle
                cx={cx}
                cy={cy}
                r={12 + riskVal * 12}
                fill={color}
                fillOpacity="0.12"
                stroke={color}
                strokeWidth="1.5"
                strokeOpacity="0.6"
                onMouseMove={(e) =>
                  handleMouseMove(
                    e,
                    <div>
                      <strong style={{ fontSize: 13, color: '#f3f4f6' }}>{zone.label}</strong>
                      <div style={{ color, fontWeight: 700, marginTop: 4 }}>
                        Geopolitical Risk Score: {riskVal.toFixed(3)}
                      </div>
                      {zone.situation && (
                        <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 4, maxWidth: 200, whiteSpace: 'normal', lineHeight: 1.4 }}>
                          {zone.situation.slice(0, 80)}...
                        </div>
                      )}
                    </div>
                  )
                }
                onMouseLeave={handleMouseLeave}
              />
            </g>
          );
        })}

        {/* Shipping Route Lines */}
        {waypoints && waypoints.length >= 2 && (
          <g>
            {/* Glowing route line backdrop */}
            <path
              d={makeRoutePath(waypoints)}
              fill="none"
              stroke="#22d3ee"
              strokeWidth="5"
              strokeLinecap="round"
              strokeLinejoin="round"
              opacity="0.2"
              style={{ filter: 'blur(3px)' }}
            />
            {/* Main vector route path with dash drawing animation */}
            <path
              d={makeRoutePath(waypoints)}
              fill="none"
              stroke="#22d3ee"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="svg-active-route"
            />
          </g>
        )}

        {/* Port Nodes (Origin and Destination pins) */}
        {origin && (
          <g transform={`translate(${projectLng(origin.coords[1])}, ${projectLat(origin.coords[0])})`}>
            <circle
              r="6"
              fill="#10b981"
              stroke="#fff"
              strokeWidth="1.5"
              style={{ filter: 'drop-shadow(0 0 4px #10b981)' }}
              onMouseMove={(e) =>
                handleMouseMove(
                  e,
                  <div>
                    <strong>⚓ Origin Port</strong>
                    <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 2 }}>{origin.name}</div>
                  </div>
                )
              }
              onMouseLeave={handleMouseLeave}
            />
            <text y="-10" textAnchor="middle" fill="#10b981" fontSize="9" fontWeight="700">ORIGIN</text>
          </g>
        )}

        {destination && (
          <g transform={`translate(${projectLng(destination.coords[1])}, ${projectLat(destination.coords[0])})`}>
            <circle
              r="6"
              fill="#ef4444"
              stroke="#fff"
              strokeWidth="1.5"
              style={{ filter: 'drop-shadow(0 0 4px #ef4444)' }}
              onMouseMove={(e) =>
                handleMouseMove(
                  e,
                  <div>
                    <strong>🏁 Destination Port</strong>
                    <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 2 }}>{destination.name}</div>
                  </div>
                )
              }
              onMouseLeave={handleMouseLeave}
            />
            <text y="-10" textAnchor="middle" fill="#ef4444" fontSize="9" fontWeight="700">DESTINATION</text>
          </g>
        )}
      </svg>

      {/* Floating vector map tooltip */}
      {tooltip && (
        <div
          style={{
            position: 'absolute',
            left: tooltip.x,
            top: tooltip.y,
            background: 'rgba(15, 23, 42, 0.95)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            padding: '8px 12px',
            pointerEvents: 'none',
            zIndex: 1000,
            boxShadow: 'var(--shadow-lg)',
            fontSize: 12,
            fontFamily: 'Inter, sans-serif',
          }}
        >
          {tooltip.content}
        </div>
      )}
    </div>
  );
}
