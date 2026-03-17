"""
upload_xmls.py -- Upload en masse de fichiers IOF XML (+OCAD optionnel) vers AItraceur
=======================================================================================
Usage :
  cd backend
  python upload_xmls.py <dossier_ou_fichier> [niveau_iof] [type_carte] [categorie]

Exemples :
  python upload_xmls.py E:/Vikazim/AItraceur/xml sprint urban H21E
  python upload_xmls.py E:/Vikazim/AItraceur/xml middle forest D16
  python upload_xmls.py E:/Vikazim/AItraceur/xml long forest H21E

Arguments :
  niveau_iof  : sprint | middle | long
  type_carte  : urban | forest
  categorie   : H10..H80 | D10..D75 | H21E | D21E | Open | Mixte

Le script detecte automatiquement :
  - Tous les fichiers .xml du dossier
  - Pour chaque .xml, cherche un .ocd de meme nom dans le meme dossier
  - Si trouve, envoie les deux ensemble pour enrichir les features terrain
"""

import sys
import os
import requests

BACKEND_URL = "http://localhost:8000/api/v1/contribute"


def find_ocd_for_xml(xml_path: str) -> str | None:
    """
    Cherche un fichier .ocd associe au XML dans le meme dossier.
    Strategies :
      1. meme nom sans extension (parcours.Courses.xml -> parcours.ocd)
      2. premier segment du nom (parcours.Courses.xml -> parcours.ocd)
      3. n'importe quel .ocd unique dans le dossier
    """
    folder = os.path.dirname(xml_path)
    xml_name = os.path.basename(xml_path)
    base = xml_name.rsplit(".", 1)[0]

    candidate = os.path.join(folder, base + ".ocd")
    if os.path.isfile(candidate):
        return candidate

    stem = base.split(".")[0]
    candidate2 = os.path.join(folder, stem + ".ocd")
    if os.path.isfile(candidate2):
        return candidate2

    ocd_files = [f for f in os.listdir(folder) if f.lower().endswith(".ocd")]
    if len(ocd_files) == 1:
        return os.path.join(folder, ocd_files[0])

    return None


def upload_xml(xml_path: str, ocd_path: str = None, circuit_type: str = None,
               map_type: str = None, ffco_category: str = None):
    xml_filename = os.path.basename(xml_path)
    data = {"consent_aitraceur": "true"}
    if circuit_type:
        data["circuit_type"] = circuit_type
    if map_type:
        data["map_type"] = map_type
    if ffco_category:
        data["ffco_category"] = ffco_category

    files = {"xml_file": (xml_filename, open(xml_path, "rb"), "application/xml")}
    if ocd_path:
        files["ocd_file"] = (os.path.basename(ocd_path), open(ocd_path, "rb"), "application/octet-stream")

    try:
        resp = requests.post(BACKEND_URL, files=files, data=data, timeout=60)
    finally:
        for f in files.values():
            f[1].close()

    if resp.status_code == 200:
        r = resp.json()
        terrain = " +terrain" if ocd_path else ""
        n_circuits = r.get("n_circuits", 1)
        circuits_label = f"{n_circuits} circuits, " if n_circuits > 1 else ""
        extra = ""
        circuits = r.get("circuits", [])
        if circuits and n_circuits > 1:
            detected = [f"{c.get('name','?')}({c.get('color_detected') or '?'})" for c in circuits]
            extra = f" [{', '.join(detected)}]"
        return True, f"{circuits_label}{r.get('n_controls_extracted', '?')} postes, TD{r.get('td_grade', '?')}{terrain}{extra}, id={r.get('contribution_id')}"
    elif resp.status_code == 409:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        return False, f"DOUBLON — {detail}"
    else:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        return False, detail


def main():
    if len(sys.argv) < 2:
        print("Usage : python upload_xmls.py <dossier> [niveau_iof] [type_carte] [couleur] [categorie]")
        print("Exemple : python upload_xmls.py E:/xml sprint urban bleu H21E")
        sys.exit(1)

    path_arg    = sys.argv[1]
    circuit_type   = sys.argv[2] if len(sys.argv) >= 3 else None
    map_type       = sys.argv[3] if len(sys.argv) >= 4 else None
    ffco_category  = sys.argv[4] if len(sys.argv) >= 5 else None

    if os.path.isfile(path_arg) and path_arg.lower().endswith(".xml"):
        xml_files = [path_arg]
    elif os.path.isdir(path_arg):
        folder = path_arg
        xml_files = [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith(".xml")
        ]
    else:
        print(f"Introuvable : {path_arg}")
        sys.exit(1)

    if not xml_files:
        print(f"Aucun fichier .xml trouve dans : {path_arg}")
        sys.exit(1)

    pairs = []
    for xml_path in sorted(xml_files):
        ocd_path = find_ocd_for_xml(xml_path)
        pairs.append((xml_path, ocd_path))

    n_with_ocd = sum(1 for _, ocd in pairs if ocd)
    print(f"=== Upload AItraceur — {len(pairs)} fichier(s) ===")
    if circuit_type:  print(f"Niveau IOF  : {circuit_type}")
    if map_type:      print(f"Carte       : {map_type}")
    if ffco_category: print(f"Categorie   : {ffco_category}")
    if n_with_ocd:
        print(f"OCAD        : {n_with_ocd}/{len(pairs)} circuits avec .ocd (features terrain)")
    else:
        print("OCAD        : aucun .ocd trouve")
    print(f"Backend     : {BACKEND_URL}")
    print()

    ok_count = 0
    for i, (xml_path, ocd_path) in enumerate(pairs, 1):
        xml_name = os.path.basename(xml_path)
        ocd_label = f" + {os.path.basename(ocd_path)}" if ocd_path else ""
        print(f"[{i}/{len(pairs)}] {xml_name}{ocd_label} ... ", end="", flush=True)
        try:
            success, msg = upload_xml(xml_path, ocd_path, circuit_type, map_type, ffco_category)
            if success:
                print(f"OK  ({msg})")
                ok_count += 1
            else:
                print(f"ECHEC  -- {msg}")
        except requests.exceptions.ConnectionError:
            print("ECHEC  -- Backend non joignable (uvicorn demarre ?)")
            sys.exit(1)
        except Exception as e:
            print(f"ECHEC  -- {e}")

    print()
    print(f"=== Resultat : {ok_count}/{len(pairs)} uploades avec succes ===")
    if ok_count > 0:
        print()
        print("Inspecter l'extraction :")
        print("  python inspect_data.py")


if __name__ == "__main__":
    main()
