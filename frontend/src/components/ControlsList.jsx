import { useState, useEffect } from 'react';
import { getCourseElevation } from '../services/api';

const IOF_COLOR = '#9b2cae';

const TYPE_LABELS = {
  start: 'Départ',
  control: 'Poste',
  finish: 'Arrivée',
};

const TypeIcon = ({ type }) => {
  if (type === 'start') {
    return (
      <svg width="14" height="14" viewBox="0 0 14 14" className="flex-shrink-0">
        <polygon points="7,1 13,13 1,13" fill="none" stroke={IOF_COLOR} strokeWidth="1.5" strokeLinejoin="round" />
      </svg>
    );
  }
  if (type === 'finish') {
    return (
      <svg width="14" height="14" viewBox="0 0 14 14" className="flex-shrink-0">
        <circle cx="7" cy="7" r="6" fill="none" stroke={IOF_COLOR} strokeWidth="1.5" />
        <circle cx="7" cy="7" r="3.5" fill="none" stroke={IOF_COLOR} strokeWidth="1.5" />
      </svg>
    );
  }
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" className="flex-shrink-0">
      <circle cx="7" cy="7" r="6" fill="none" stroke={IOF_COLOR} strokeWidth="1.5" />
    </svg>
  );
};

function ElevationProfile({ elevations }) {
  const alts = elevations.map(e => e.elevation);
  const minAlt = Math.min(...alts);
  const maxAlt = Math.max(...alts);
  const range = maxAlt - minAlt || 1;
  const W = 220, H = 44, PAD = 4;

  const pts = alts.map((alt, i) => {
    const x = PAD + (i / (alts.length - 1)) * (W - PAD * 2);
    const y = H - PAD - ((alt - minAlt) / range) * (H - PAD * 2);
    return [x, y];
  });

  const polylinePoints = pts.map(([x, y]) => `${x},${y}`).join(' ');
  const areaPoints = `${PAD},${H - PAD} ${polylinePoints} ${W - PAD},${H - PAD}`;

  return (
    <div className="mt-2 p-2 bg-gray-800/50 rounded-lg">
      <p className="text-[10px] text-gray-500 mb-1.5 flex justify-between">
        <span>Profil d'altitude</span>
        <span>{Math.round(minAlt)}–{Math.round(maxAlt)} m</span>
      </p>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: H }}>
        <polygon points={areaPoints} fill={IOF_COLOR} fillOpacity="0.12" />
        <polyline
          points={polylinePoints}
          fill="none"
          stroke={IOF_COLOR}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {pts.map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r="2" fill={IOF_COLOR} />
        ))}
      </svg>
    </div>
  );
}

const ControlsList = ({ controls, onDelete, totalDistance, controlCount, onShowRoutes, activeRouteLegIdx }) => {
  const [climbData, setClimbData] = useState(null);
  const [loadingClimb, setLoadingClimb] = useState(false);

  const ordered = [...controls]
    .filter(c => ['start', 'control', 'finish'].includes(c.type))
    .sort((a, b) => a.order - b.order);

  // Reset D+ when controls are added or removed
  useEffect(() => {
    setClimbData(null);
  }, [controls.length]);

  const formatDistance = (metres) => {
    if (metres >= 1000) return `${(metres / 1000).toFixed(1)} km`;
    return `${metres} m`;
  };

  const getLabel = (control, index) => {
    if (control.type === 'start') return 'S';
    if (control.type === 'finish') return 'F';
    const controlsBefore = ordered.slice(0, index).filter(c => c.type === 'control').length;
    return String(controlsBefore + 1);
  };

  const fetchClimb = async () => {
    if (ordered.length < 2 || loadingClimb) return;
    setLoadingClimb(true);
    try {
      const payload = ordered.map(c => ({ lat: c.lat, lng: c.lng, order: c.order }));
      const res = await getCourseElevation(payload);
      setClimbData(res.data);
    } catch {
      // silent — D+ stays null
    } finally {
      setLoadingClimb(false);
    }
  };

  return (
    <div className="bg-gray-700/50 p-4 rounded-xl border border-gray-700">
      {/* Header with stats */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-200">Parcours</h2>
        <div className="flex items-center gap-2 text-xs flex-wrap justify-end">
          <span className="text-gray-400">{controlCount} poste{controlCount !== 1 ? 's' : ''}</span>
          {totalDistance > 0 && (
            <span className="text-blue-400">~{formatDistance(totalDistance)}</span>
          )}
          {climbData && (
            <span className="text-amber-400 font-medium">+{climbData.total_climb_m}m D+</span>
          )}
          {ordered.length >= 2 && (
            <button
              onClick={fetchClimb}
              disabled={loadingClimb}
              title="Calculer le dénivelé"
              className="text-gray-500 hover:text-amber-400 transition-colors disabled:opacity-40 ml-0.5"
            >
              {loadingClimb ? (
                <span className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin inline-block" />
              ) : (
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                </svg>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Control list */}
      {ordered.length > 0 ? (
        <div className="space-y-0.5">
          {ordered.map((control, index) => (
            <div key={control.id}>
              <div className="flex items-start gap-2 p-2 rounded-lg bg-gray-800/60 hover:bg-gray-800 group transition-colors">
                <TypeIcon type={control.type} />
                <span className="text-xs font-mono text-gray-400 w-5 text-center mt-0.5">
                  {getLabel(control, index)}
                </span>
                <div className="flex-1 min-w-0">
                  <span className="text-xs text-gray-300">
                    {TYPE_LABELS[control.type]}
                  </span>
                  {/* Description IOF colonne D (FFCO 2018) */}
                  {control.description && control.description !== 'Position libre' && (
                    <p className="text-[10px] text-violet-400/80 truncate leading-tight mt-0.5" title={control.description}>
                      {control.description}
                    </p>
                  )}
                </div>
                {/* Altitude au poste si disponible */}
                {climbData?.elevations && (() => {
                  const ev = climbData.elevations.find(e => e.order === control.order);
                  return ev ? (
                    <span className="text-[10px] text-gray-500 mr-1 mt-0.5">{Math.round(ev.elevation)}m</span>
                  ) : null;
                })()}
                <button
                  onClick={() => onDelete(control.id)}
                  className="opacity-0 group-hover:opacity-100 transition-opacity text-gray-500 hover:text-red-400 p-0.5 rounded"
                  title="Supprimer"
                  aria-label={`Supprimer ${TYPE_LABELS[control.type]}`}
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              {/* Séparateur de jambe avec bouton Route Analyzer */}
              {index < ordered.length - 1 && onShowRoutes && (
                <div className="flex items-center gap-1 py-0.5 px-2">
                  <div className="flex-1 h-px bg-gray-700/60" />
                  <button
                    onClick={() => onShowRoutes(index, control, ordered[index + 1])}
                    title="Voir les itinéraires possibles"
                    className={`text-[10px] px-1.5 py-0.5 rounded transition-colors ${
                      activeRouteLegIdx === index
                        ? 'bg-blue-600 text-white'
                        : 'text-gray-600 hover:text-blue-400 hover:bg-gray-700'
                    }`}
                  >
                    🔍
                  </button>
                  <div className="flex-1 h-px bg-gray-700/60" />
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-gray-500 text-center py-2">
          Placez des postes sur la carte
        </p>
      )}

      {/* Elevation profile */}
      {climbData?.elevations?.length >= 2 && (
        <ElevationProfile elevations={climbData.elevations} />
      )}
    </div>
  );
};

export default ControlsList;
