import React, { useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';

const CorridorMap = ({ hormuzRisk, redSeaRisk, onSelectCorridor }) => {
  const [expandedExplanation, setExpandedExplanation] = useState({});

  const corridors = [
    {
      id: 'hormuz',
      name: 'Strait of Hormuz',
      coordinates: [26.5, 56.3],
      riskData: hormuzRisk,
    },
    {
      id: 'red_sea',
      name: 'Red Sea / Bab-el-Mandeb',
      coordinates: [12.6, 43.4],
      riskData: redSeaRisk,
    },
  ];

  const getRiskColor = (score) => {
    if (score === null || score === undefined) return '#9ca3af'; // gray
    if (score < 0.4) return '#10b981'; // green (emerald)
    if (score <= 0.7) return '#f59e0b'; // amber
    return '#ef4444'; // red (rose)
  };

  const getMarkerRadius = (score) => {
    if (score === null || score === undefined) return 10;
    return 10 + score * 25; // Scale from 10px to 35px
  };

  const handleMarkerClick = (corridorId) => {
    onSelectCorridor(corridorId);
  };

  const toggleExpand = (e, corridorId) => {
    e.stopPropagation();
    setExpandedExplanation((prev) => ({
      ...prev,
      [corridorId]: !prev[corridorId],
    }));
  };

  return (
    <div className="map-panel">
      <div className="panel-header">
        <h3 className="panel-title">Geospatial Risk Monitor</h3>
        <span className="panel-subtitle">Interactive chokepoints tracking</span>
      </div>
      <div className="map-wrapper" style={{ height: '400px', width: '100%', borderRadius: '8px', overflow: 'hidden' }}>
        <MapContainer
          center={[20, 50]}
          zoom={4}
          style={{ height: '100%', width: '100%' }}
          scrollWheelZoom={true}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          />
          {corridors.map((c) => {
            const score = c.riskData?.risk_score;
            const confidence = c.riskData?.confidence;
            const explanation = c.riskData?.explanation || 'No assessment data available for this corridor.';
            const color = getRiskColor(score);
            const radius = getMarkerRadius(score);

            const isExpanded = expandedExplanation[c.id];
            const truncatedText = explanation.length > 150 ? explanation.slice(0, 150) + '...' : explanation;

            return (
              <CircleMarker
                key={c.id}
                center={c.coordinates}
                radius={radius}
                fillColor={color}
                color={color}
                weight={2}
                opacity={0.8}
                fillOpacity={0.4}
                eventHandlers={{
                  click: () => handleMarkerClick(c.id),
                }}
              >
                <Popup>
                  <div className="map-popup">
                    <h4>{c.name}</h4>
                    <div className="popup-stat-row">
                      <div>
                        <strong>Risk Score:</strong>{' '}
                        <span style={{ color }}>{score !== undefined && score !== null ? score.toFixed(2) : 'N/A'}</span>
                      </div>
                      <div>
                        <strong>Confidence:</strong>{' '}
                        <span>{confidence !== undefined && confidence !== null ? `${(confidence * 100).toFixed(0)}%` : 'N/A'}</span>
                      </div>
                    </div>
                    <div className="popup-explanation">
                      <p>{isExpanded ? explanation : truncatedText}</p>
                      {explanation.length > 150 && (
                        <button
                          className="popup-expand-btn"
                          onClick={(e) => toggleExpand(e, c.id)}
                        >
                          {isExpanded ? 'Show less' : 'Read more'}
                        </button>
                      )}
                    </div>
                  </div>
                </Popup>
              </CircleMarker>
            );
          })}
        </MapContainer>
      </div>
    </div>
  );
};

export default CorridorMap;
