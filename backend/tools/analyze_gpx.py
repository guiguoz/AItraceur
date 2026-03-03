"""
Outil CLI : analyse multi-GPX depuis un dossier.

Usage :
    cd backend
    python tools/analyze_gpx.py chemin/vers/dossier_gpx/

Options :
    --save      Sauvegarder la calibration terrain dans terrain_calibration.json
    --radius N  Rayon de snap GPS→poste en mètres (défaut: 50)
    --api URL   URL du backend (défaut: http://localhost:8000)

Exemples :
    python tools/analyze_gpx.py C:/Users/moi/gpx_livelox/
    python tools/analyze_gpx.py ./gpx/ --save --radius 80
"""

import argparse
import glob
import json
import os
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Analyse consensus de traces GPX CO (vitesse/jambe, difficulté, calibration terrain)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("gpx_dir", help="Dossier contenant les fichiers .gpx")
    parser.add_argument("--save", action="store_true", help="Sauvegarder la calibration terrain")
    parser.add_argument("--radius", type=float, default=50.0, help="Rayon snap GPS→poste en mètres (défaut: 50)")
    parser.add_argument("--api", default="http://localhost:8000", help="URL du backend AItraceur")
    args = parser.parse_args()

    # Trouver les fichiers GPX
    gpx_dir = os.path.abspath(args.gpx_dir)
    gpx_files = sorted(glob.glob(os.path.join(gpx_dir, "*.gpx")))

    if len(gpx_files) < 2:
        print(f"[ERREUR] Il faut au moins 2 fichiers .gpx dans '{gpx_dir}'")
        print(f"         Trouvé : {len(gpx_files)} fichier(s)")
        sys.exit(1)

    print(f"[OK] {len(gpx_files)} fichiers GPX trouvés dans {gpx_dir}")

    # Vérifier que le backend tourne
    try:
        import urllib.request
        urllib.request.urlopen(f"{args.api}/health", timeout=3)
    except Exception:
        print(f"[ERREUR] Backend inaccessible à {args.api}")
        print("         Lance d'abord : cd backend && uvicorn src.main:app --reload")
        sys.exit(1)

    # Appel direct aux fonctions Python (sans HTTP) pour plus de simplicité
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from src.services.analysis.gpx_parser import parse_gpx, extract_waypoints
    from src.services.analysis.multi_gpx_analyzer import analyze_multi_gpx, save_terrain_calibration

    # Lire et parser tous les GPX
    gpx_tracks = []
    raw_contents = []
    for path in gpx_files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            raw_contents.append(content)
            track = parse_gpx(content)
            if track:
                gpx_tracks.append(track)
                print(f"  ✓ {os.path.basename(path)} — {len(track)} points GPS")
            else:
                print(f"  ✗ {os.path.basename(path)} — GPX vide ou invalide")
        except Exception as e:
            print(f"  ✗ {os.path.basename(path)} — Erreur : {e}")

    if len(gpx_tracks) < 2:
        print(f"\n[ERREUR] Seulement {len(gpx_tracks)} track(s) valide(s) parsée(s). Minimum 2 requis.")
        sys.exit(1)

    # Extraire les postes depuis les waypoints du premier GPX qui en a
    controls = []
    for raw in raw_contents:
        wpts = extract_waypoints(raw)
        if len(wpts) >= 2:
            controls = [{"x": w["lon"], "y": w["lat"], "order": i} for i, w in enumerate(wpts)]
            print(f"\n[OK] {len(controls)} postes extraits des waypoints GPX")
            for i, c in enumerate(controls):
                name = wpts[i].get("name", "")
                print(f"     Poste {i}: ({c['y']:.5f}, {c['x']:.5f}){' — ' + name if name else ''}")
            break

    if not controls:
        print("\n[INFO] Aucun waypoint trouvé dans les GPX.")
        print("       L'analyse se fera sans découpage par jambe")
        print("       (vitesse globale + consensus de tracé seulement)")

    # Lancer l'analyse
    print(f"\n[...] Analyse de {len(gpx_tracks)} coureurs ({len(controls)} postes, rayon snap {args.radius}m)...")
    result = analyze_multi_gpx(
        gpx_tracks=gpx_tracks,
        controls=controls,
        snap_radius_m=args.radius,
    )

    # Afficher les résultats
    print(f"\n{'='*60}")
    print(f"RÉSULTATS — {result['runners_analyzed']} coureur(s) analysé(s), {result['legs_analyzed']} jambe(s)")
    print(f"{'='*60}")

    if result["speed_per_leg"]:
        has_global = "global" in result["speed_per_leg"]
        if has_global:
            stats = result["speed_per_leg"]["global"]
            print(f"\nVitesse globale (course entière, {stats['runners']} coureurs) :")
            print(f"  moy={stats['mean']:.0f}, médiane={stats['median']:.0f}, σ={stats['std']:.0f} m/min")
            print("  (Sans postes — pas de découpage par jambe)")
        else:
            print("\nVitesse par jambe (m/min) :")
            def _leg_sort(x):
                try:
                    return int(x[0])
                except ValueError:
                    return 9999
            for leg, stats in sorted(result["speed_per_leg"].items(), key=_leg_sort):
                cv = result["difficulty_per_leg"].get(leg, 0)
                difficulty = "⚡ DIFFICILE" if cv > 0.3 else ("~ moyen" if cv > 0.15 else "✓ facile")
                print(f"  Jambe {leg}: moy={stats['mean']:.0f}, médiane={stats['median']:.0f}, "
                      f"σ={stats['std']:.0f} m/min — {difficulty} (CV={cv:.2f})")
    else:
        print("\n[INFO] Pas d'analyse (aucune trace valide avec timestamps)")

    if result.get("consensus_path", {}).get("global"):
        n_cells = len(result["consensus_path"]["global"])
        print(f"\nConsensus de tracé : {n_cells} cellules 20m×20m fréquentées (≥10% des coureurs)")

    if result.get("avoided_zones"):
        print(f"\nZones évitées : {len(result['avoided_zones'])} cellules 20m×20m")

    if result.get("terrain_calibration"):
        print(f"\nCalibration terrain ({len(result['terrain_calibration'])} types) :")
        for terrain, mult in sorted(result["terrain_calibration"].items()):
            print(f"  {terrain}: {mult:.3f}")

    # Sauvegarder si demandé
    if args.save and result.get("terrain_calibration"):
        saved = save_terrain_calibration(
            result["terrain_calibration"],
            result["runners_analyzed"],
            source=f"cli:{gpx_dir}",
        )
        print(f"\n{'[OK]' if saved else '[ERREUR]'} Calibration {'sauvegardée' if saved else 'NON sauvegardée'} dans terrain_calibration.json")
    elif args.save:
        print("\n[INFO] --save demandé mais pas de calibration terrain (fournir --ocad ou GeoJSON OCAD)")

    # Sauvegarder le JSON complet
    out_path = os.path.join(gpx_dir, "analyse_consensus.json")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\n[OK] Résultats complets sauvegardés : {out_path}")
    except OSError as e:
        print(f"\n[WARN] Impossible d'écrire le JSON : {e}")

    print()


if __name__ == "__main__":
    main()
