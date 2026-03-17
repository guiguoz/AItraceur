import React, { useState, useRef } from 'react';
import ocad2geojson from 'ocad2geojson';
import { Buffer } from 'buffer';
import { reprojectToWgs84 } from '../services/ocadCrs';

const API_BASE = 'http://localhost:8000/api/v1';


/**
 * Formulaire de contribution de circuits pour l'apprentissage ML.
 * - Upload IOF XML (obligatoire) + OCAD optionnel (pour features terrain)
 * - Consentement RGPD explicite
 * - Suppression immédiate des fichiers bruts côté serveur
 */
const ContributeForm = ({ onClose }) => {
  const [xmlFile, setXmlFile] = useState(null);
  const [ocadFile, setOcadFile] = useState(null);
  const [circuitType, setCircuitType] = useState('');
  const [mapType, setMapType] = useState('');
  const [ffcoCategory, setFfcoCategory] = useState('');
  const [consentAitraceur, setConsentAitraceur] = useState(false);
  const [consentEducational, setConsentEducational] = useState(false);
  const [status, setStatus] = useState(null); // null | 'loading' | 'success' | 'error'
  const [result, setResult] = useState(null);
  const [errorMsg, setErrorMsg] = useState('');
  const [deleteId, setDeleteId] = useState('');
  const [deleteStatus, setDeleteStatus] = useState(null);

  const xmlRef = useRef(null);
  const ocadRef = useRef(null);

  // ---- Soumission ----
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!xmlFile) { setErrorMsg('Veuillez fournir un fichier IOF XML.'); return; }
    if (!circuitType) { setErrorMsg('Veuillez indiquer le niveau IOF (sprint / moyenne / longue distance).'); return; }
    if (!mapType) { setErrorMsg('Veuillez indiquer le type de carte (urbaine / forêt).'); return; }
    if (!ffcoCategory) { setErrorMsg('Veuillez indiquer la catégorie FFCO/IOF (ex: H21E, D16, Open).'); return; }
    if (!consentAitraceur) { setErrorMsg('Vous devez accepter le consentement obligatoire.'); return; }

    setStatus('loading');
    setErrorMsg('');

    try {
      // Extraire GeoJSON terrain depuis OCAD (optionnel, côté client)
      let geojsonData = null;
      if (ocadFile) {
        try {
          const buf = await ocadFile.arrayBuffer();
          const ocadData = await ocad2geojson(Buffer.from(buf));
          const reprojected = reprojectToWgs84(ocadData);
          geojsonData = JSON.stringify(reprojected);
        } catch {
          // Silencieux — l'OCAD est optionnel
        }
      }

      const formData = new FormData();
      formData.append('xml_file', xmlFile);
      if (geojsonData) formData.append('geojson_data', geojsonData);
      if (circuitType) formData.append('circuit_type', circuitType);
      if (mapType) formData.append('map_type', mapType);
      if (ffcoCategory) formData.append('ffco_category', ffcoCategory);
      formData.append('consent_aitraceur', 'true');
      formData.append('consent_educational', consentEducational ? 'true' : 'false');

      const resp = await fetch(`${API_BASE}/contribute`, {
        method: 'POST',
        body: formData,
      });
      const data = await resp.json();

      if (!resp.ok) throw new Error(data.detail || 'Erreur serveur');

      setResult(data);
      setStatus('success');
    } catch (err) {
      setErrorMsg(err.message);
      setStatus('error');
    }
  };

  // ---- Suppression RGPD ----
  const handleDelete = async () => {
    if (!deleteId) return;
    setDeleteStatus('loading');
    try {
      const resp = await fetch(`${API_BASE}/contribute/${deleteId}`, { method: 'DELETE' });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || 'Introuvable');
      setDeleteStatus('success');
    } catch (err) {
      setDeleteStatus(err.message);
    }
  };

  return (
    <div style={styles.overlay}>
      <div style={styles.modal}>
        <div style={styles.header}>
          <h2 style={styles.title}>Contribuer à l'apprentissage d'AItraceur</h2>
          {onClose && <button onClick={onClose} style={styles.closeBtn}>✕</button>}
        </div>

        <div style={styles.body}>
          {/* Bandeau info */}
          <div style={styles.infoBanner}>
            <strong>Comment ça fonctionne :</strong> Vos fichiers sont analysés
            immédiatement, les données statistiques anonymisées sont conservées,
            et les fichiers originaux sont <strong>supprimés définitivement</strong>.
            Aucune coordonnée GPS n'est stockée.
          </div>

          <form onSubmit={handleSubmit}>
            {/* IOF XML */}
            <label style={styles.label}>
              Fichier IOF XML 3.0 <span style={styles.required}>*</span>
              <input
                ref={xmlRef}
                type="file"
                accept=".xml"
                style={styles.fileInput}
                onChange={e => setXmlFile(e.target.files[0] || null)}
              />
            </label>
            {xmlFile && <div style={styles.fileName}>📄 {xmlFile.name}</div>}

            {/* OCAD optionnel */}
            <label style={styles.label}>
              Carte OCAD (.ocd) — optionnel
              <span style={styles.hint}> (améliore les features terrain)</span>
              <input
                ref={ocadRef}
                type="file"
                accept=".ocd"
                style={styles.fileInput}
                onChange={e => setOcadFile(e.target.files[0] || null)}
              />
            </label>
            {ocadFile && <div style={styles.fileName}>🗺 {ocadFile.name}</div>}

            {/* Niveau IOF */}
            <label style={styles.label}>
              Niveau IOF <span style={styles.required}>*</span>
              <div style={styles.radioRow}>
                {[['sprint', 'Sprint'], ['middle', 'Moyenne distance'], ['long', 'Longue distance']].map(([v, l]) => (
                  <label key={v} style={styles.radioLabel}>
                    <input type="radio" name="circuitType" value={v} checked={circuitType === v} onChange={() => setCircuitType(v)} />
                    {' '}{l}
                  </label>
                ))}
              </div>
            </label>

            {/* Type de carte */}
            <label style={styles.label}>
              Type de carte <span style={styles.required}>*</span>
              <div style={styles.radioRow}>
                {[['urban', 'Urbaine'], ['forest', 'Forêt']].map(([v, l]) => (
                  <label key={v} style={styles.radioLabel}>
                    <input type="radio" name="mapType" value={v} checked={mapType === v} onChange={() => setMapType(v)} />
                    {' '}{l}
                  </label>
                ))}
              </div>
            </label>

            {/* Catégorie FFCO/IOF */}
            <label style={styles.label}>
              Catégorie FFCO/IOF <span style={styles.required}>*</span>
              <span style={styles.hint}> (qui court ce circuit ?)</span>
              <select
                value={ffcoCategory}
                onChange={e => setFfcoCategory(e.target.value)}
                style={styles.select}
              >
                <option value="">— Sélectionner —</option>
                <optgroup label="Hommes">
                  {['H10','H12','H14','H16','H18','H20','H21E','H21A','H21B','H35','H40','H45','H50','H55','H60','H65','H70','H75','H80'].map(c => <option key={c} value={c}>{c}</option>)}
                </optgroup>
                <optgroup label="Dames">
                  {['D10','D12','D14','D16','D18','D20','D21E','D21A','D21B','D35','D40','D45','D50','D55','D60','D65','D70','D75'].map(c => <option key={c} value={c}>{c}</option>)}
                </optgroup>
                <optgroup label="Autres">
                  <option value="Open">Open</option>
                  <option value="Mixte">Mixte</option>
                </optgroup>
                <optgroup label="Circuits couleur">
                  <option value="Jaune">Jaune</option>
                  <option value="Orange">Orange</option>
                  <option value="Vert">Vert</option>
                  <option value="Bleu">Bleu</option>
                  <option value="Violet">Violet</option>
                </optgroup>
              </select>
            </label>

            {/* Consentement obligatoire */}
            <div style={styles.consentBox}>
              <label style={styles.consentLabel}>
                <input
                  type="checkbox"
                  checked={consentAitraceur}
                  onChange={e => setConsentAitraceur(e.target.checked)}
                  style={styles.checkbox}
                />
                <span>
                  <strong>J'autorise l'usage de ces données pour améliorer AItraceur</strong>
                  <span style={styles.required}> *</span>
                  <br />
                  <small style={styles.consentText}>
                    Les fichiers sont supprimés immédiatement après extraction des données
                    statistiques anonymisées. Aucune coordonnée GPS ni identifiant n'est
                    conservé. Vous pouvez demander la suppression de votre contribution
                    à tout moment avec l'identifiant fourni après dépôt (art. 17 RGPD).
                  </small>
                </span>
              </label>
            </div>

            {/* Consentement éducatif */}
            <div style={styles.consentBox}>
              <label style={styles.consentLabel}>
                <input
                  type="checkbox"
                  checked={consentEducational}
                  onChange={e => setConsentEducational(e.target.checked)}
                  style={styles.checkbox}
                />
                <span>
                  J'autorise le partage des données anonymisées à des fins éducatives
                  (licence CC BY-NC 4.0 — jamais commercial)
                  <br />
                  <small style={styles.hint}>Optionnel. Permet à des chercheurs en CO d'accéder aux statistiques.</small>
                </span>
              </label>
            </div>

            {/* Note GPX */}
            <div style={styles.gpxNote}>
              <strong>Note sur les traces GPX :</strong> Si vous souhaitez contribuer
              des traces de coureurs (.gpx), envoyez un email à{' '}
              <em>[contact à définir]</em>. Les traces GPX contiennent des données
              personnelles (localisation horodatée) — elles sont traitées avec votre
              consentement explicite et supprimées dans les 24h.
            </div>

            {errorMsg && <div style={styles.error}>{errorMsg}</div>}

            <button
              type="submit"
              disabled={status === 'loading'}
              style={styles.submitBtn}
            >
              {status === 'loading' ? 'Envoi en cours…' : 'Contribuer'}
            </button>
          </form>

          {/* Résultat succès */}
          {status === 'success' && result && (
            <div style={styles.successBox}>
              <strong>Merci pour votre contribution !</strong><br />
              {result.n_circuits > 1
                ? <>{result.n_circuits} circuits extraits — {result.n_controls_extracted} postes au total</>
                : <>{result.n_controls_extracted} postes, TD{result.td_grade}</>
              }
              {result.circuits && result.circuits.length > 0 && (
                <ul style={{marginTop: 8, paddingLeft: 18, fontSize: 12}}>
                  {result.circuits.map((c, i) => (
                    <li key={i}>
                      <strong>{c.name || `Circuit ${i+1}`}</strong> — {c.n_controls} postes
                      {c.color_detected && <> · couleur détectée : <em>{c.color_detected}</em></>}
                      {c.category_detected && <> · catégorie : <em>{c.category_detected}</em></>}
                    </li>
                  ))}
                </ul>
              )}
              <br />
              <strong>Identifiant(s) de contribution : {result.contribution_ids ? result.contribution_ids.map(id => `#${id}`).join(', ') : `#${result.contribution_id}`}</strong><br />
              <small>Conservez ces identifiants pour exercer votre droit à l'effacement (art. 17 RGPD).</small>
            </div>
          )}

          {/* Droit à l'effacement */}
          <hr style={styles.hr} />
          <div style={styles.deleteSection}>
            <h3 style={styles.deleteTitle}>Supprimer ma contribution (RGPD)</h3>
            <div style={styles.deleteRow}>
              <input
                type="number"
                placeholder="Identifiant de contribution"
                value={deleteId}
                onChange={e => setDeleteId(e.target.value)}
                style={styles.deleteInput}
              />
              <button
                onClick={handleDelete}
                disabled={!deleteId || deleteStatus === 'loading'}
                style={styles.deleteBtn}
              >
                Supprimer
              </button>
            </div>
            {deleteStatus === 'success' && (
              <div style={styles.successBox}>Contribution supprimée.</div>
            )}
            {deleteStatus && deleteStatus !== 'success' && deleteStatus !== 'loading' && (
              <div style={styles.error}>{deleteStatus}</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

// ---- Styles inline minimalistes ----
const styles = {
  overlay: { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' },
  modal: { background: '#fff', borderRadius: 8, width: 560, maxWidth: '95vw', maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 4px 24px rgba(0,0,0,0.2)' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 20px', borderBottom: '1px solid #e0e0e0' },
  title: { margin: 0, fontSize: 17, color: '#333' },
  closeBtn: { background: 'none', border: 'none', fontSize: 18, cursor: 'pointer', color: '#666' },
  body: { padding: '16px 20px 20px' },
  infoBanner: { background: '#f0f7ff', border: '1px solid #b3d4f5', borderRadius: 6, padding: '10px 14px', marginBottom: 16, fontSize: 13, color: '#1a4a7a' },
  label: { display: 'block', fontSize: 13, fontWeight: 600, color: '#444', marginBottom: 12 },
  fileInput: { display: 'block', marginTop: 6, fontSize: 13 },
  fileName: { fontSize: 12, color: '#555', marginTop: -8, marginBottom: 10 },
  select: { display: 'block', marginTop: 6, padding: '6px 10px', borderRadius: 4, border: '1px solid #ccc', width: '100%', fontSize: 13 },
  hint: { color: '#888', fontWeight: 400 },
  required: { color: '#c00' },
  consentBox: { background: '#fafafa', border: '1px solid #e0e0e0', borderRadius: 6, padding: '10px 14px', marginBottom: 10 },
  consentLabel: { display: 'flex', gap: 10, cursor: 'pointer', fontSize: 13 },
  checkbox: { marginTop: 2, flexShrink: 0 },
  consentText: { color: '#666', lineHeight: 1.5 },
  gpxNote: { background: '#fffbea', border: '1px solid #f0d060', borderRadius: 6, padding: '10px 14px', fontSize: 12, color: '#7a5a00', marginBottom: 16 },
  error: { background: '#fff0f0', border: '1px solid #f5a0a0', borderRadius: 4, padding: '8px 12px', color: '#900', fontSize: 13, marginBottom: 10 },
  submitBtn: { background: '#9b2cae', color: '#fff', border: 'none', borderRadius: 6, padding: '10px 24px', fontSize: 14, cursor: 'pointer', width: '100%' },
  successBox: { background: '#f0fff4', border: '1px solid #6fcf97', borderRadius: 6, padding: '12px 16px', color: '#1a5c35', fontSize: 13, marginTop: 12 },
  hr: { margin: '20px 0', borderColor: '#e0e0e0' },
  deleteSection: {},
  deleteTitle: { fontSize: 14, color: '#555', marginBottom: 10 },
  deleteRow: { display: 'flex', gap: 8 },
  deleteInput: { flex: 1, padding: '8px 10px', border: '1px solid #ccc', borderRadius: 4, fontSize: 13 },
  deleteBtn: { padding: '8px 16px', background: '#c0392b', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 13 },
  radioRow: { display: 'flex', gap: 16, marginTop: 6, flexWrap: 'wrap' },
  radioLabel: { fontSize: 13, fontWeight: 400, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 },
};

export default ContributeForm;
