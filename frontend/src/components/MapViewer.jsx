import { useEffect, useRef, useMemo, useState } from 'react';
import { MapContainer, TileLayer, ImageOverlay, Marker, Popup, useMap, useMapEvents, Polyline, Polygon } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// IOF/ISOM course overlay color (magenta-purple)
const IOF_COLOR = '#9b2cae';
const SUGGESTION_COLOR = '#7c3aed';
const ICON_SIZE = 32;


// Create IOF-standard control icons using inline SVG
const createControlIcon = (type, order) => {
  const STROKE = 2.5;
  let svgContent;

  if (type === 'start') {
    svgContent = `
      <svg width="${ICON_SIZE}" height="${ICON_SIZE}" viewBox="0 0 ${ICON_SIZE} ${ICON_SIZE}" xmlns="http://www.w3.org/2000/svg">
        <polygon points="16,3 30,29 2,29" fill="none" stroke="${IOF_COLOR}" stroke-width="${STROKE}" stroke-linejoin="round"/>
      </svg>`;
  } else if (type === 'finish') {
    svgContent = `
      <svg width="${ICON_SIZE}" height="${ICON_SIZE}" viewBox="0 0 ${ICON_SIZE} ${ICON_SIZE}" xmlns="http://www.w3.org/2000/svg">
        <circle cx="16" cy="16" r="13" fill="none" stroke="${IOF_COLOR}" stroke-width="${STROKE}"/>
        <circle cx="16" cy="16" r="9" fill="none" stroke="${IOF_COLOR}" stroke-width="${STROKE}"/>
      </svg>`;
  } else {
    const displayNum = order > 1 ? order - 1 : order;
    svgContent = `
      <svg width="${ICON_SIZE}" height="${ICON_SIZE}" viewBox="0 0 ${ICON_SIZE} ${ICON_SIZE}" xmlns="http://www.w3.org/2000/svg">
        <circle cx="16" cy="16" r="13" fill="none" stroke="${IOF_COLOR}" stroke-width="${STROKE}"/>
        <text x="16" y="21" text-anchor="middle" font-size="11" font-weight="bold" font-family="sans-serif" fill="${IOF_COLOR}">${displayNum}</text>
      </svg>`;
  }

  return L.divIcon({ className: '', html: svgContent, iconSize: [ICON_SIZE, ICON_SIZE], iconAnchor: [ICON_SIZE / 2, ICON_SIZE / 2], popupAnchor: [0, -(ICON_SIZE / 2)] });
};

// Create AI suggestion marker icon (purple, draggable indicator)
const createSuggestionIcon = (type) => {
  const S = ICON_SIZE + 8;
  const cx = S / 2;
  let svgContent;

  if (type === 'start') {
    svgContent = `
      <svg width="${S}" height="${S}" viewBox="0 0 ${S} ${S}" xmlns="http://www.w3.org/2000/svg">
        <polygon points="${cx},3 ${S-3},${S-3} 3,${S-3}" fill="${SUGGESTION_COLOR}" fill-opacity="0.25" stroke="${SUGGESTION_COLOR}" stroke-width="2.5" stroke-linejoin="round"/>
      </svg>`;
  } else if (type === 'finish') {
    svgContent = `
      <svg width="${S}" height="${S}" viewBox="0 0 ${S} ${S}" xmlns="http://www.w3.org/2000/svg">
        <circle cx="${cx}" cy="${cx}" r="${cx-3}" fill="${SUGGESTION_COLOR}" fill-opacity="0.25" stroke="${SUGGESTION_COLOR}" stroke-width="2.5"/>
        <circle cx="${cx}" cy="${cx}" r="${cx-8}" fill="none" stroke="${SUGGESTION_COLOR}" stroke-width="2.5"/>
      </svg>`;
  } else {
    svgContent = `
      <svg width="${S}" height="${S}" viewBox="0 0 ${S} ${S}" xmlns="http://www.w3.org/2000/svg">
        <circle cx="${cx}" cy="${cx}" r="${cx-3}" fill="${SUGGESTION_COLOR}" fill-opacity="0.25" stroke="${SUGGESTION_COLOR}" stroke-width="2.5"/>
        <text x="${cx}" y="${cx+4}" text-anchor="middle" font-size="13" font-weight="bold" font-family="sans-serif" fill="${SUGGESTION_COLOR}">?</text>
      </svg>`;
  }

  return L.divIcon({ className: '', html: svgContent, iconSize: [S, S], iconAnchor: [S / 2, S / 2] });
};

// Dispatch map clicks between control placement and forbidden zone drawing
function MapEvents({ onControlClick, onForbiddenClick, activeTool }) {
  useMapEvents({
    click(e) {
      if (activeTool === 'view') return;
      if (activeTool === 'forbidden') {
        onForbiddenClick?.(e.latlng);
      } else {
        onControlClick?.(e.latlng);
      }
    },
  });
  return null;
}


// Auto-fit bounds when map or image loads
function FitBounds({ bounds }) {
  const map = useMap();
  useEffect(() => {
    if (!bounds) return;
    try {
      const lb = bounds instanceof L.LatLngBounds ? bounds : L.latLngBounds(bounds);
      if (lb.isValid()) map.fitBounds(lb, { padding: [50, 50] });
    } catch (e) {}
  }, [bounds, map]);
  return null;
}

// Expose Leaflet map instance to parent via callback
function MapRefCapture({ onReady }) {
  const map = useMap();
  useEffect(() => { onReady?.(map); }, [map, onReady]);
  return null;
}

// Create a custom pane above ImageOverlay so forbidden zones are always visible
function CreateForbiddenPane() {
  const map = useMap();
  useEffect(() => {
    if (!map.getPane('forbiddenPane')) {
      map.createPane('forbiddenPane');
      map.getPane('forbiddenPane').style.zIndex = 450;  // above overlayPane (400) and imageOverlay
    }
  }, [map]);
  return null;
}

// Pan map to AI suggestion when it changes
function PanToSuggestion({ suggestion }) {
  const map = useMap();
  useEffect(() => {
    if (!suggestion?.lat || !suggestion?.lng) return;
    map.flyTo([suggestion.lat, suggestion.lng], Math.max(map.getZoom(), 15), {
      duration: 0.6,
    });
  }, [suggestion, map]);
  return null;
}

// Route display colors — rank 1 blue, rank 2 orange, rank 3 red
const ROUTE_STYLES = [
  { color: '#3b82f6', weight: 4, opacity: 0.9, dashArray: null },
  { color: '#f59e0b', weight: 3, opacity: 0.75, dashArray: '8 5' },
  { color: '#ef4444', weight: 3, opacity: 0.6, dashArray: '5 5' },
];

export function MapViewer({
  ocadData = null,
  onMapClick,
  controls = [],
  forbiddenZones = [],
  currentSuggestion = null,
  activeTool = 'view',
  imageData = null,
  onAddForbiddenZone,
  onUpdateSuggestion,
  onMapReady = null,
  navigationQuality = [],  // [{from_idx, to_idx, nav_score, ...}] — coloration par jambe
  navContext = null,  // {attack_point, catching_feature, handrail_samples, optimal_route, decision_points}
  ocadMode = false,  // true → masque OSM, affiche uniquement PNG OCAD
  backgroundControls = [],  // mode compétition — postes des autres circuits
}) {
  // Polygon drawing — local intermediate state
  const [drawingVertices, setDrawingVertices] = useState([]);

  // Clear drawing when switching away from forbidden tool
  useEffect(() => {
    if (activeTool !== 'forbidden') setDrawingVertices([]);
  }, [activeTool]);

  const handleForbiddenClick = (latlng) => {
    // [lat, lng] pour Leaflet (affichage)
    setDrawingVertices(prev => [...prev, [latlng.lat, latlng.lng]]);
  };

  const handleClosePolygon = () => {
    if (drawingVertices.length >= 3) {
      // Convertir en [lng, lat] (GeoJSON standard) pour le backend
      const polygon = drawingVertices.map(([lat, lng]) => [lng, lat]);
      onAddForbiddenZone?.(polygon);
    }
    setDrawingVertices([]);
  };

  // Bounds for auto-fit
  const finalBounds = useMemo(() => {
    if (!ocadData?.geojson?.features?.length) return null;
    let minLat = Infinity, maxLat = -Infinity, minLng = Infinity, maxLng = -Infinity;
    const walk = (coords) => {
      if (typeof coords[0] === 'number') {
        if (minLng > coords[0]) minLng = coords[0];
        if (maxLng < coords[0]) maxLng = coords[0];
        if (minLat > coords[1]) minLat = coords[1];
        if (maxLat < coords[1]) maxLat = coords[1];
      } else coords.forEach(walk);
    };
    ocadData.geojson.features.forEach(f => f.geometry?.coordinates && walk(f.geometry.coordinates));
    if (!isFinite(minLat)) return null;
    return L.latLngBounds([minLat, minLng], [maxLat, maxLng]);
  }, [ocadData]);

  // Ordered positions for the course polyline — includes currentSuggestion to preview last leg.
  // During ai_suggesting: exclude existing finish (may have small order from previous circuit)
  // so it doesn't appear in the middle of the polyline. currentSuggestion is appended last.
  // finish is always sorted last regardless of its order field.
  const baseForLine = currentSuggestion
    ? controls.filter(c => c.type !== 'finish')
    : controls
  // Re-append user-placed finish after currentSuggestion so the last leg is drawn.
  // (finish was removed from baseForLine to avoid stale order, but must come last.)
  const userFinish = currentSuggestion
    ? controls.find(c => c.type === 'finish')
    : null
  const allForLine = currentSuggestion
    ? [
        ...baseForLine,
        { ...currentSuggestion, order: baseForLine.length + 1 },
        ...(userFinish ? [{ ...userFinish, order: baseForLine.length + 2 }] : [])
      ]
    : controls
  const orderedPositions = allForLine
    .filter(c => ['start', 'control', 'finish'].includes(c.type))
    .sort((a, b) => {
      if (a.type === 'finish' && b.type !== 'finish') return 1
      if (b.type === 'finish' && a.type !== 'finish') return -1
      return a.order - b.order
    })
    .map(c => [c.lat, c.lng]);

  return (
    <div
      className="w-full h-full relative"
      style={{ cursor: activeTool !== 'view' ? 'crosshair' : 'grab' }}
    >
      <MapContainer
        center={[46.6034, 1.8883]}
        zoom={6}
        className="w-full h-full"
      >
        <MapRefCapture onReady={onMapReady} />
        <CreateForbiddenPane />
        <MapEvents
          onControlClick={onMapClick}
          onForbiddenClick={handleForbiddenClick}
          activeTool={activeTool}
        />

        {/* OSM base layer — masqué en mode OCAD, atténué en mode mixte */}
        {!ocadMode && (
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            opacity={imageData ? 0.25 : 1}
          />
        )}

        <FitBounds bounds={imageData ? imageData.bounds : finalBounds} />
        <PanToSuggestion suggestion={currentSuggestion} />

        {/* OCAD map as georeferenced PNG — fond principal en mode OCAD */}
        {imageData && (
          <ImageOverlay url={imageData.url} bounds={imageData.bounds} opacity={1} zIndex={10} />
        )}

        {/* Completed forbidden zones — red dashed polygons */}
        {/* forbiddenZones stockées en [lng,lat] (backend) → convertir en [lat,lng] pour Leaflet */}
        {forbiddenZones.map((zone, i) => (
          <Polygon
            key={`fz-${i}`}
            positions={zone.map(([lng, lat]) => [lat, lng])}
            pane="forbiddenPane"
            pathOptions={{ color: '#cc0000', fillColor: '#cc0000', fillOpacity: 0.25, weight: 2.5, dashArray: '6 4' }}
          />
        ))}

        {/* Forbidden zone being drawn — preview polyline */}
        {drawingVertices.length >= 2 && (
          <Polyline
            positions={drawingVertices}
            pane="forbiddenPane"
            pathOptions={{ color: '#cc0000', weight: 2.5, dashArray: '6 4', opacity: 0.9 }}
          />
        )}

        {/* Vertex markers while drawing */}
        {drawingVertices.map((v, i) => (
          <Marker
            key={`dv-${i}`}
            position={v}
            icon={L.divIcon({
              className: '',
              html: `<div style="width:8px;height:8px;border-radius:50%;background:#cc0000;border:2px solid white;margin-top:-4px;margin-left:-4px"></div>`,
              iconSize: [1, 1],
              iconAnchor: [0, 0],
            })}
          />
        ))}

        {/* Course polyline — par jambe colorée si nav quality disponible, sinon magenta IOF */}
        {orderedPositions.length >= 2 && navigationQuality.length > 0
          ? orderedPositions.slice(0, -1).map((pos, i) => {
              const leg = navigationQuality[i]
              const score = leg?.nav_score ?? null
              const color = score === null ? IOF_COLOR
                : score >= 0.7 ? '#22c55e'
                : score >= 0.4 ? '#f59e0b'
                : '#ef4444'
              return (
                <Polyline
                  key={`leg-nav-${i}`}
                  positions={[pos, orderedPositions[i + 1]]}
                  pathOptions={{ color, weight: 2, opacity: 0.9 }}
                >
                  <Popup>
                    <div className="text-xs">
                      <strong>Jambe {i + 1}</strong><br />
                      {leg?.attack_score != null && <>Attaque : {leg.attack_score.toFixed(2)}<br /></>}
                      {leg?.catch_score != null && <>Arrêt : {leg.catch_score.toFixed(2)}<br /></>}
                      {leg?.handrail_score != null && <>Main c. : {leg.handrail_score.toFixed(2)}<br /></>}
                      {score != null && <>Nav score : {score.toFixed(2)}</>}
                    </div>
                  </Popup>
                </Polyline>
              )
            })
          : orderedPositions.length >= 2 && (
              <Polyline
                positions={orderedPositions}
                pathOptions={{ color: IOF_COLOR, weight: 2, opacity: 0.85 }}
              />
            )
        }


        {/* Background controls — autres circuits (mode compétition)
            Dédupliqués par id : une balise partagée (départ/arrivée) a le même id
            dans le circuit actif → on ne l'affiche pas en doublon. */}
        {backgroundControls
          .filter(bg => !controls.some(ac => ac.id && bg.id && ac.id === bg.id))
          .map((ctrl, i) => (
          <Marker
            key={`bg_${i}`}
            position={[ctrl.lat, ctrl.lng]}
            icon={L.divIcon({
              className: '',
              html: `<div style="width:20px;height:20px;border:2px solid #888;border-radius:50%;background:rgba(136,136,136,0.15);box-sizing:border-box;"></div>`,
              iconSize: [20, 20],
              iconAnchor: [10, 10],
            })}
          >
            <Popup><div className="text-xs text-gray-500">{ctrl.circuitName || 'Autre circuit'}</div></Popup>
          </Marker>
        ))}

        {/* Control markers with IOF/ISOM symbols */}
        {controls.map((control) => (
          <Marker
            key={control.id}
            position={[control.lat, control.lng]}
            icon={createControlIcon(control.type, control.order)}
          >
            <Popup>
              <div className="text-sm">
                <strong>
                  {control.type === 'start' ? 'Départ' : control.type === 'finish' ? 'Arrivée' : `Poste #${control.order - 1}`}
                </strong>
              </div>
            </Popup>
          </Marker>
        ))}


        {/* ── Nav Context overlays (Phase 5) ──────────────────────────────── */}

        {/* Route optimale OSM (gris pointillé) */}
        {navContext?.optimal_route?.length >= 2 && (
          <Polyline
            positions={navContext.optimal_route.map(p => [p.lat, p.lng])}
            pathOptions={{ color: '#9ca3af', weight: 3, opacity: 0.8, dashArray: '6 4' }}
          >
            <Popup><div className="text-xs">Route optimale OSM</div></Popup>
          </Polyline>
        )}

        {/* Main courante (vert) — points intermédiaires ayant une feature à ≤50m */}
        {navContext?.handrail_samples?.length >= 2 && (
          <Polyline
            positions={navContext.handrail_samples.map(p => [p.lat, p.lng])}
            pathOptions={{ color: '#22c55e', weight: 4, opacity: 0.75 }}
          >
            <Popup><div className="text-xs">Main courante</div></Popup>
          </Polyline>
        )}

        {/* Points de décision (rouge ★) */}
        {navContext?.decision_points?.map((pt, i) => (
          <Marker
            key={`dp-${i}`}
            position={[pt.lat, pt.lng]}
            icon={L.divIcon({
              className: '',
              html: `<div style="font-size:16px;line-height:1;color:#ef4444;text-shadow:0 0 3px #000">★</div>`,
              iconSize: [16, 16],
              iconAnchor: [8, 8],
            })}
          >
            <Popup><div className="text-xs">Point de décision</div></Popup>
          </Marker>
        ))}

        {/* Point d'attaque (cercle jaune) */}
        {navContext?.attack_point && (
          <Marker
            position={[navContext.attack_point.lat, navContext.attack_point.lng]}
            icon={L.divIcon({
              className: '',
              html: `<div style="width:14px;height:14px;border-radius:50%;background:#fbbf24;border:2px solid #fff;box-shadow:0 0 4px rgba(0,0,0,.6)"></div>`,
              iconSize: [14, 14],
              iconAnchor: [7, 7],
            })}
          >
            <Popup>
              <div className="text-xs">
                <strong>Point d'attaque</strong><br />
                ISOM {navContext.attack_point.isom} — score {navContext.attack_point.score?.toFixed(2)}
              </div>
            </Popup>
          </Marker>
        )}

        {/* Ligne d'arrêt (cercle bleu) */}
        {navContext?.catching_feature && (
          <Marker
            position={[navContext.catching_feature.lat, navContext.catching_feature.lng]}
            icon={L.divIcon({
              className: '',
              html: `<div style="width:14px;height:14px;border-radius:50%;background:#3b82f6;border:2px solid #fff;box-shadow:0 0 4px rgba(0,0,0,.6)"></div>`,
              iconSize: [14, 14],
              iconAnchor: [7, 7],
            })}
          >
            <Popup>
              <div className="text-xs">
                <strong>Ligne d'arrêt</strong><br />
                ISOM {navContext.catching_feature.isom} — score {navContext.catching_feature.score?.toFixed(2)}
              </div>
            </Popup>
          </Marker>
        )}

        {/* AI suggestion — draggable purple marker */}
        {currentSuggestion && (
          <Marker
            key="ai-suggestion"
            position={[currentSuggestion.lat, currentSuggestion.lng]}
            icon={createSuggestionIcon(currentSuggestion.type)}
            draggable={true}
            eventHandlers={{
              dragend: (e) => {
                const { lat, lng } = e.target.getLatLng();
                onUpdateSuggestion?.({ lat, lng });
              },
            }}
          />
        )}
      </MapContainer>

      {/* "Close polygon" floating button — appears when drawing has ≥3 vertices */}
      {activeTool === 'forbidden' && drawingVertices.length >= 3 && (
        <button
          onClick={handleClosePolygon}
          className="absolute bottom-6 left-1/2 -translate-x-1/2 z-[1000] bg-red-700 hover:bg-red-600 text-white text-sm font-medium px-5 py-2.5 rounded-full shadow-xl flex items-center gap-2 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          Fermer la zone ({drawingVertices.length} sommets)
        </button>
      )}
    </div>
  );
}
