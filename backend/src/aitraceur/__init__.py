"""
aitraceur — Moteur sémantique de génération de circuits de CO.

Architecture en 7 couches :
  1. controls/    — Candidats postes (ControlCandidate)
  2. navigation/  — Modèle de déplacement (graphe + raster)
  3. matrix/      — Matrice de coûts entre candidats
  4. model/       — Modèle de parcours (Course)
  5. scoring/     — Fonction de scoring explicable
  6. generation/  — Génération constructive + optimisation locale + GA
  7. calibration/ — Calibration sur circuits de référence

Point d'entrée rapide :
    from aitraceur.profiles import PROFILE_FOREST_MIDDLE_ORANGE
    from aitraceur.controls.generator import generate_control_candidates
    from aitraceur.generation.constructive import generate_initial_course
    from aitraceur.scoring.scorer import score_course
"""
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("aitraceur")
except PackageNotFoundError:
    __version__ = "dev"

__all__ = ["__version__"]
