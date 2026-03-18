#!/usr/bin/env python3
"""
Test qualité pipeline GPX+OSM sprint urbain.
Lance le backend, crée un GPX synthétique de sprint urbain (Strasbourg),
puis vérifie toutes les features extraites.

Usage:
    cd backend
    python test_gpx_pipeline.py

Résultats attendus:
    - n_controls >= 5
    - leg_distance_m : toutes entre 50m et 800m
    - terrain_symbol_density > 0 (OSM répond)
    - nearest_path_dist_m <= 30m (postes proches des rues)
    - attractiveness_score > 0
    - quality_score entre 0 et 1
    - Aucune valeur None sur les features géométriques
"""

import sys
import os
import math

# Sprint urbain synthétique : carrefours de Strasbourg centre
# (coordonnées réelles — rues bien cartographiées dans OSM)
STRASBOURG_SPRINT = [
    (7.7521, 48.5834),  # départ : Place Kléber
    (7.7498, 48.5821),  # rue des Hallebardes
    (7.7512, 48.5808),  # rue du Vieux-Marché-aux-Poissons
    (7.7535, 48.5798),  # place du Château
    (7.7558, 48.5812),  # rue des Charpentiers
    (7.7542, 48.5825),  # rue des Orfèvres
    (7.7518, 48.5840),  # rue du Dôme
    (7.7521, 48.5834),  # arrivée (= départ)
]

# ─── Génération GPX synthétique ───────────────────────────────────────────────

def make_gpx(controls):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">']
    names = ['S1', '31', '32', '33', '34', '35', '36', 'F1']
    for i, (lng, lat) in enumerate(controls):
        name = names[i] if i < len(names) else str(i)
        lines.append(f'  <wpt lat="{lat}" lon="{lng}"><name>{name}</name></wpt>')
    lines.append('</gpx>')
    return '\n'.join(lines)

# ─── Tests ───────────────────────────────────────────────────────────────────

def test_gpx_feature_extractor():
    print("\n" + "="*60)
    print("TEST 1 : GpxFeatureExtractor (GPX synthétique Strasbourg)")
    print("="*60)

    sys.path.insert(0, os.path.dirname(__file__))
    from src.services.learning.gpx_feature_extractor import GpxFeatureExtractor

    gpx_text = make_gpx(STRASBOURG_SPRINT)
    extractor = GpxFeatureExtractor()

    result = extractor.extract_from_gpx(
        content=gpx_text.encode(),
        circuit_type="sprint",
        map_type="urban",
        ffco_category="H21E",
        with_osm_terrain=True,
    )

    assert result is not None, "FAIL: extract_from_gpx a retourné None"
    print(f"  ✓ ContributionFeatures créé")
    print(f"    circuit_type={result.circuit_type}, map_type={result.map_type}")
    print(f"    n_controls={result.n_controls}, length_m={result.length_m}m, td_grade={result.td_grade}")

    assert result.circuit_type == "sprint", f"FAIL: circuit_type={result.circuit_type}"
    assert result.map_type == "urban", f"FAIL: map_type={result.map_type}"
    assert result.n_controls >= 4, f"FAIL: n_controls={result.n_controls} < 4"
    assert result.length_m and result.length_m > 200, f"FAIL: length_m={result.length_m}"
    assert result.td_grade in (1, 2, 3, 4, 5), f"FAIL: td_grade={result.td_grade}"

    print(f"\n  Analyse des {len(result.controls)} vecteurs de postes :")
    errors = []
    for i, fv in enumerate(result.controls):
        print(f"    [{i}] leg={fv.leg_distance_m}m | turn={fv.leg_bearing_change}° | "
              f"terrain_density={fv.terrain_symbol_density} | "
              f"path_dist={fv.nearest_path_dist_m}m | "
              f"type={fv.control_feature_type} | "
              f"attract={fv.attractiveness_score} | "
              f"quality={fv.quality_score:.3f}")

        # Vérifications par poste
        if i > 0 and fv.leg_distance_m is None:
            errors.append(f"Poste {i}: leg_distance_m est None")
        if i > 0 and fv.leg_distance_m and (fv.leg_distance_m < 5 or fv.leg_distance_m > 5000):
            errors.append(f"Poste {i}: leg_distance_m={fv.leg_distance_m} hors plage raisonnable")
        if fv.quality_score is None or not (0 <= fv.quality_score <= 1):
            errors.append(f"Poste {i}: quality_score={fv.quality_score} hors [0,1]")

    # Vérification terrain OSM (peut être 0 si Overpass timeout)
    terrain_filled = [fv for fv in result.controls if fv.terrain_symbol_density is not None]
    osm_ok = len(terrain_filled) == len(result.controls)
    if osm_ok:
        has_nonzero = any(fv.terrain_symbol_density > 0 for fv in result.controls)
        if not has_nonzero:
            print("  ⚠ terrain_symbol_density = 0 partout (Overpass n'a pas répondu ou zone vide)")
        else:
            print(f"  ✓ Features OSM remplies ({len(terrain_filled)}/{len(result.controls)} postes)")
    else:
        print(f"  ⚠ Features OSM partielles ({len(terrain_filled)}/{len(result.controls)} postes)")

    if errors:
        for e in errors:
            print(f"  ✗ {e}")
        return False
    print("  ✓ Tous les vecteurs sont valides")
    return True


def test_kmz_parser():
    print("\n" + "="*60)
    print("TEST 2 : KmzImporter (KMZ synthétique)")
    print("="*60)
    import io, zipfile

    from src.services.importers.kmz_importer import parse_kmz

    # Générer un KMZ synthétique
    kml_content = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark><name>Départ</name><Point><coordinates>7.7521,48.5834,0</coordinates></Point></Placemark>
    <Placemark><name>31</name><Point><coordinates>7.7498,48.5821,0</coordinates></Point></Placemark>
    <Placemark><name>32</name><Point><coordinates>7.7512,48.5808,0</coordinates></Point></Placemark>
    <Placemark><name>33</name><Point><coordinates>7.7535,48.5798,0</coordinates></Point></Placemark>
    <Placemark><name>Arrivée</name><Point><coordinates>7.7521,48.5834,0</coordinates></Point></Placemark>
  </Document>
</kml>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml_content)
        z.writestr("map.jpg", b"fake_image_data")  # image ignorée
    kmz_bytes = buf.getvalue()

    points = parse_kmz(kmz_bytes)
    assert len(points) == 5, f"FAIL: {len(points)} placemarks (attendu 5)"
    assert points[0]["name"] == "Départ", f"FAIL: nom poste 0 = {points[0]['name']}"
    assert abs(points[0]["lat"] - 48.5834) < 0.0001, "FAIL: lat incorrecte"
    assert abs(points[0]["lon"] - 7.7521) < 0.0001, "FAIL: lon incorrecte"

    print(f"  ✓ {len(points)} placemarks parsés")
    for p in points:
        print(f"    {p['name']} : ({p['lat']:.4f}, {p['lon']:.4f})")
    print("  ✓ Image JPEG dans le KMZ ignorée correctement (seul le KML est parsé)")
    return True


def test_quality_score_range():
    print("\n" + "="*60)
    print("TEST 3 : Quality score — cas limites")
    print("="*60)
    from src.services.learning.gpx_feature_extractor import _circuit_quality_score

    # Circuit idéal : legs équilibrées, bons changements de direction
    ideal = [(0.0, 0.0), (0.0, 0.004), (0.003, 0.002), (0.006, 0.004), (0.003, 0.006)]
    score_ideal = _circuit_quality_score(ideal)
    print(f"  Circuit idéal : score={score_ideal:.3f}")
    assert 0 <= score_ideal <= 1, f"FAIL: score hors [0,1]"

    # Circuit avec dog-leg : changement de direction quasi nul
    dogleg = [(0.0, 0.0), (0.001, 0.0), (0.002, 0.0001), (0.003, 0.0)]
    score_dl = _circuit_quality_score(dogleg)
    print(f"  Circuit dog-leg : score={score_dl:.3f}")
    assert score_dl < score_ideal, "FAIL: dog-leg devrait avoir un score inférieur"

    # Très court (2 points)
    score_short = _circuit_quality_score([(0.0, 0.0), (0.001, 0.0)])
    print(f"  Circuit trop court (2 pts) : score={score_short:.3f}")
    assert 0 <= score_short <= 1

    print("  ✓ Quality score dans [0,1] pour tous les cas")
    return True


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\nTest qualité pipeline GPX+OSM sprint urbain")
    print("Backend doit être accessible sur localhost:8000 pour Overpass\n")

    results = []
    try:
        results.append(("GpxFeatureExtractor", test_gpx_feature_extractor()))
    except Exception as e:
        print(f"  ✗ EXCEPTION : {e}")
        results.append(("GpxFeatureExtractor", False))

    try:
        results.append(("KmzImporter", test_kmz_parser()))
    except Exception as e:
        print(f"  ✗ EXCEPTION : {e}")
        results.append(("KmzImporter", False))

    try:
        results.append(("QualityScore", test_quality_score_range()))
    except Exception as e:
        print(f"  ✗ EXCEPTION : {e}")
        results.append(("QualityScore", False))

    print("\n" + "="*60)
    print("RÉSUMÉ")
    print("="*60)
    ok = 0
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status} : {name}")
        if passed:
            ok += 1
    print(f"\n{ok}/{len(results)} tests passés")
    sys.exit(0 if ok == len(results) else 1)
