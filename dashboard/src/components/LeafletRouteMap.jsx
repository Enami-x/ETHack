/**
 * LeafletRouteMap.jsx
 *
 * Real interactive map powered by Leaflet.js + react-leaflet.
 * Uses CartoDB Dark Matter tiles (free, no API key).
 *
 * Props:
 *   origin            — { name, coords: [lat, lng] }
 *   destination       — { name, coords: [lat, lng] }
 *   waypoints         — [[lat, lng], ...] for the active route
 *   allRoutes         — [{ id, name, waypoints, recommendation }, ...] optional alternative routes
 *   corridorRiskZones — [{ id, label, coords, risk, situation }]
 *   activeOptionId    — string id of the selected route
 *   onSelectCorridor  — optional callback(corridorId)
 */
import { useEffect, useRef } from 'react';
import {
  MapContainer,
  TileLayer,
  Polyline,
  CircleMarker,
  Circle,
  Tooltip,
  useMap,
} from 'react-leaflet';
import 'leaflet/dist/leaflet.css';

// ── risk colour helper ────────────────────────────────────────────────────────
function riskColor(score) {
  if (!score || score < 0.35) return '#22c55e';   // green
  if (score < 0.65)           return '#f59e0b';   // amber
  if (score < 0.80)           return '#f97316';   // orange
  return '#ef4444';                                // red
}

// ── Fit map bounds to all coordinates shown ───────────────────────────────────
function BoundsFitter({ waypoints, origin, destination, corridorRiskZones }) {
  const map = useMap();

  useEffect(() => {
    const pts = [];
    if (waypoints?.length) waypoints.forEach(w => pts.push(w));
    if (origin?.coords)      pts.push(origin.coords);
    if (destination?.coords) pts.push(destination.coords);
    corridorRiskZones?.forEach(z => pts.push(z.coords));

    if (pts.length < 2) {
      // Default: centre on Middle East shipping lanes
      map.setView([20, 55], 3);
      return;
    }

    try {
      const L = window.L || require('leaflet');
      const bounds = L.latLngBounds(pts);
      map.fitBounds(bounds.pad(0.15), { maxZoom: 6 });
    } catch {
      map.setView([20, 55], 3);
    }
  }, [waypoints, origin, destination, corridorRiskZones, map]);

  return null;
}

export default function LeafletRouteMap({
  origin          = null,
  destination     = null,
  waypoints       = [],
  allRoutes       = [],
  corridorRiskZones = [],
  activeOptionId  = null,
  onSelectCorridor = null,
}) {
  const hasRoute = waypoints && waypoints.length >= 2;

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        minHeight: 420,
        borderRadius: 10,
        overflow: 'hidden',
        border: '1.5px solid var(--border)',
        position: 'relative',
      }}
    >
      <MapContainer
        center={[20, 50]}
        zoom={3}
        scrollWheelZoom={true}
        style={{ width: '100%', height: '100%', minHeight: 420, background: '#0d1117' }}
        zoomControl={true}
        attributionControl={false}
      >
        {/* Dark tile layer */}
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          subdomains="abcd"
          maxZoom={19}
        />

        {/* Auto-fit bounds */}
        <BoundsFitter
          waypoints={waypoints}
          origin={origin}
          destination={destination}
          corridorRiskZones={corridorRiskZones}
        />

        {/* ── Risk corridor overlays ──────────────────────────────────── */}
        {corridorRiskZones.map(zone => {
          const color = riskColor(zone.risk);
          const radiusM = (zone.radius_km ?? 150) * 1000;
          return (
            <Circle
              key={zone.id}
              center={zone.coords}
              radius={radiusM}
              pathOptions={{
                color,
                fillColor: color,
                fillOpacity: 0.08,
                weight: 1.5,
                dashArray: '6 4',
                opacity: 0.55,
              }}
              eventHandlers={{
                click: () => onSelectCorridor && onSelectCorridor(zone.id),
              }}
            >
              <Tooltip sticky>
                <div style={{ fontSize: 12, lineHeight: 1.5, maxWidth: 220 }}>
                  <strong style={{ fontSize: 13 }}>{zone.label}</strong>
                  <div style={{ color, fontWeight: 700, marginTop: 2 }}>
                    Risk Score: {(zone.risk ?? 0).toFixed(3)}
                  </div>
                  {zone.situation && (
                    <div style={{ color: '#9ca3af', marginTop: 4, fontSize: 11 }}>
                      {zone.situation.slice(0, 120)}…
                    </div>
                  )}
                </div>
              </Tooltip>
            </Circle>
          );
        })}

        {/* ── Alternative routes (grey dashed) ───────────────────────── */}
        {allRoutes
          .filter(r => r.id !== activeOptionId && r.waypoints?.length >= 2)
          .map(r => (
            <Polyline
              key={r.id}
              positions={r.waypoints}
              pathOptions={{
                color: '#6b7280',
                weight: 1.5,
                dashArray: '6 5',
                opacity: 0.5,
              }}
            >
              <Tooltip sticky>
                <span style={{ fontSize: 11 }}>{r.name}</span>
              </Tooltip>
            </Polyline>
          ))}

        {/* ── Active route — glowing cyan polyline ───────────────────── */}
        {hasRoute && (
          <>
            {/* Glow backdrop */}
            <Polyline
              positions={waypoints}
              pathOptions={{
                color: '#22d3ee',
                weight: 9,
                opacity: 0.12,
                lineCap: 'round',
                lineJoin: 'round',
              }}
            />
            {/* Main route line */}
            <Polyline
              positions={waypoints}
              pathOptions={{
                color: '#22d3ee',
                weight: 2.5,
                opacity: 0.95,
                lineCap: 'round',
                lineJoin: 'round',
              }}
            />
            {/* Waypoint dots */}
            {waypoints.slice(1, -1).map((wp, i) => (
              <CircleMarker
                key={i}
                center={wp}
                radius={3}
                pathOptions={{
                  color: '#22d3ee',
                  fillColor: '#22d3ee',
                  fillOpacity: 0.7,
                  weight: 1,
                }}
              />
            ))}
          </>
        )}

        {/* ── Corridor-map-only default line (no route selected) ─────── */}
        {!hasRoute && corridorRiskZones.length > 0 && corridorRiskZones.length >= 2 && (
          <Polyline
            positions={[
              [26.7, 50.1],   // Ras Tanura
              [26.5, 56.3],   // Hormuz
              [12.6, 43.4],   // Bab-el-Mandeb
              [30.5, 32.5],   // Suez
              [34.0, 20.0],   // Mediterranean
              [36.0, -5.3],   // Gibraltar
            ]}
            pathOptions={{
              color: '#f59e0b',
              weight: 1.5,
              dashArray: '4 6',
              opacity: 0.35,
            }}
          />
        )}

        {/* ── Origin port pin ─────────────────────────────────────────── */}
        {origin?.coords && (
          <CircleMarker
            center={origin.coords}
            radius={8}
            pathOptions={{
              color: '#fff',
              weight: 2,
              fillColor: '#22c55e',
              fillOpacity: 1,
            }}
          >
            <Tooltip permanent direction="top" offset={[0, -10]}>
              <span style={{ fontWeight: 700, fontSize: 11 }}>⚓ {origin.name}</span>
            </Tooltip>
          </CircleMarker>
        )}

        {/* ── Destination port pin ────────────────────────────────────── */}
        {destination?.coords && (
          <CircleMarker
            center={destination.coords}
            radius={8}
            pathOptions={{
              color: '#fff',
              weight: 2,
              fillColor: '#ef4444',
              fillOpacity: 1,
            }}
          >
            <Tooltip permanent direction="top" offset={[0, -10]}>
              <span style={{ fontWeight: 700, fontSize: 11 }}>🏁 {destination.name}</span>
            </Tooltip>
          </CircleMarker>
        )}
      </MapContainer>
    </div>
  );
}
