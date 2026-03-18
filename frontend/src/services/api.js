/**
 * api.js — AItraceur API service layer
 *
 * Axios client wired to the FastAPI backend.
 * Set VITE_API_URL in .env to override the default localhost URL.
 */

import axios from 'axios';

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// ── Health ──────────────────────────────────────────────────────────────────
export const checkHealth = () => api.get('/health');

// ── Circuits ────────────────────────────────────────────────────────────────
export const listCircuits = () => api.get('/api/v1/circuits');
export const getCircuit = (id) => api.get(`/api/v1/circuits/${id}`);
export const deleteCircuit = (id) => api.delete(`/api/v1/circuits/${id}`);

// ── Map overlays ────────────────────────────────────────────────────────────
export const uploadOverlay = (file, onProgress) => {
  const formData = new FormData();
  formData.append('file', file);
  return api.post('/api/v1/maps/upload-overlay', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (evt) => {
      if (onProgress && evt.total) {
        onProgress(Math.round((evt.loaded * 100) / evt.total));
      }
    },
  });
};

// ── AI / Knowledge base ─────────────────────────────────────────────────────
export const askAI = (question) => api.post('/api/v1/knowledge/ask', { question });
export const analyzeCircuit = (id) => api.get(`/api/v1/circuits/${id}/analyze-problems`);
export const estimateTime = (id) => api.get(`/api/v1/circuits/${id}/estimate-time`);

// ── Terrain ─────────────────────────────────────────────────────────────────
export const fetchTerrainOSM = (bbox) => api.get('/api/v1/terrain/osm', { params: bbox });

// ── Generation ───────────────────────────────────────────────────────────────
export const generateCircuit = (params) =>
  api.post('/api/v1/generation/generate', params, { timeout: 120000 });

export const getSprintCandidates = (bounding_box) =>
  api.post('/api/v1/generation/sprint-candidates', { bounding_box }, { timeout: 60000 });

/**
 * Génération sprint avec dialogue traceur↔contrôleur automatique.
 * Retourne : { controls, controleur_report, dialogue, iterations, is_valid, score }
 */
export const generateSprint = (params) =>
  api.post('/api/v1/generation/generate-sprint', params, { timeout: 180000 });

// ── Terrain runnabilité ──────────────────────────────────────────────────────
export const getRunnabilityGrid = (bbox, resolution_m = 100) =>
  api.post('/api/v1/terrain/runnability-grid', { bounding_box: bbox, resolution_m }, { timeout: 60000 });

// ── Dénivelé parcours ────────────────────────────────────────────────────────
export const getCourseElevation = (controls) =>
  api.post('/api/v1/terrain/course-elevation', { controls }, { timeout: 30000 });

// ── Route Analyzer (Étape 10f) ───────────────────────────────────────────────
export const getRoutesBetweenControls = (params) =>
  api.post('/api/v1/terrain/routes-between', params, { timeout: 60000 });

// ── OCAD Analyzer (Étape 13c) ────────────────────────────────────────────────
export const analyzeOcadGeojson = (geojson) =>
  api.post('/api/v1/ocad/analyze', { geojson }, { timeout: 30000 });

// ── Render service (ocad2tiles — image unique géoréférencée) ─────────────────
export const TILE_SERVICE_URL = import.meta.env.VITE_TILE_URL || 'http://localhost:8089';

/**
 * Upload un fichier .ocd → le service rend un PNG pleine carte + retourne les bounds WGS84.
 * Réponse : { mapId, imageUrl, bounds: { southWest: [lat,lng], northEast: [lat,lng] }, ... }
 */
export const uploadOcdForRender = (file, onProgress) => {
  const formData = new FormData();
  formData.append('file', file);
  return axios.post(`${TILE_SERVICE_URL}/upload`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 180000,
    onUploadProgress: (evt) => {
      if (onProgress && evt.total) {
        onProgress(Math.round((evt.loaded * 100) / evt.total));
      }
    },
  });
};

// ── IOF XML export (client-side) ─────────────────────────────────────────────
export const exportCircuitIOF = (circuitId) =>
  api.get(`/api/v1/circuits/${circuitId}/export/iof`);

// ── Pipeline GPX+OSM (ML sprint urbain) ─────────────────────────────────────
export const contributeGpx = (file, { ffcoCategory, consentEducational } = {}) => {
  const form = new FormData();
  const ext = file.name.split('.').pop().toLowerCase();
  form.append(ext === 'kmz' ? 'kmz_file' : 'gpx_file', file);
  if (ffcoCategory) form.append('ffco_category', ffcoCategory);
  form.append('consent_aitraceur', 'true');
  form.append('consent_educational', consentEducational ? 'true' : 'false');
  return api.post('/api/v1/contribute/gpx', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  });
};

export const parseKmzCoords = (file) => {
  const form = new FormData();
  form.append('kmz_file', file);
  return api.post('/api/v1/parse-kmz', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 30000,
  });
};

export default api;
