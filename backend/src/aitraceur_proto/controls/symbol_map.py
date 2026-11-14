"""
Correspondance codes symboles OCAD → types sémantiques internes.

Supporte ISOM 2017 (forêt) et ISSprOM 2019 (sprint).
Les codes OCAD issus de ocad2geojson sont des entiers (ex : 204 = Boulder).

Deux niveaux de classification :
    SemanticCategory — catégorie large (ROCK, LANDFORM, WATER, …)
    TerrainType      — type précis (BOULDER, KNOLL, STREAM_JUNCTION, …)

Exemple :
    info = get_semantic_info(204)
    info.category    # SemanticCategory.ROCK
    info.terrain_type # TerrainType.BOULDER
    info.is_layout   # False
    info.is_forbidden # False
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SemanticCategory(str, Enum):
    """Catégorie sémantique large d'un objet cartographique."""
    LANDFORM = "LANDFORM"           # Relief, courbes de niveau
    ROCK = "ROCK"                   # Rochers, falaises, pierriers
    WATER = "WATER"                 # Eau (lacs, ruisseaux, marais)
    VEGETATION_EDGE = "VEGETATION_EDGE"  # Limites de végétation
    PATH = "PATH"                   # Chemins, sentiers, routes
    MANMADE = "MANMADE"             # Bâtiments, murs, clôtures, escaliers
    LAYOUT = "LAYOUT"               # Éléments de mise en page (nord, cadre…) → IGNORÉ
    COURSE = "COURSE"               # Éléments de tracé (poste, départ) → IGNORÉ
    FORBIDDEN = "FORBIDDEN"         # Zones interdites / infranchissables
    UNKNOWN = "UNKNOWN"


class TerrainType(str, Enum):
    """Type de terrain précis — sert à classifier ControlCandidate."""

    # Landforms
    CONTOUR = "CONTOUR"                    # courbe de niveau (ligne, ignorée comme poste)
    KNOLL = "KNOLL"                        # butte / monticule
    HILL_TOP = "HILL_TOP"                  # sommet de colline
    SADDLE = "SADDLE"                      # col / selle
    DEPRESSION = "DEPRESSION"              # dépression
    PIT = "PIT"                            # fosse
    REENTRANT = "REENTRANT"               # renfoncement / thalweg
    SPUR = "SPUR"                          # éperon / dos de terrain
    EARTHWALL = "EARTHWALL"                # talus de terre
    EARTHWALL_RUIN = "EARTHWALL_RUIN"
    EROSION_GULLY = "EROSION_GULLY"       # ravine
    BROKEN_GROUND = "BROKEN_GROUND"

    # Rocks
    CLIFF = "CLIFF"                        # falaise franchissable
    CLIFF_IMPASSABLE = "CLIFF_IMPASSABLE" # falaise infranchissable
    BOULDER = "BOULDER"                    # bloc / rocher isolé
    BOULDER_CLUSTER = "BOULDER_CLUSTER"   # amas de rochers
    ROCKY_GROUND = "ROCKY_GROUND"         # terrain rocheux
    STONY_SLOW = "STONY_SLOW"            # pierreux (lent)
    STONY_FIGHT = "STONY_FIGHT"          # pierreux (très difficile)
    BARE_ROCK = "BARE_ROCK"              # roche nue

    # Water
    OPEN_WATER = "OPEN_WATER"             # lac / étang
    STREAM = "STREAM"                      # ruisseau/fossé franchissable
    STREAM_IMPASSABLE = "STREAM_IMPASSABLE"
    MARSH = "MARSH"                        # marécage
    MARSH_IMPASSABLE = "MARSH_IMPASSABLE"
    SPRING = "SPRING"                      # source / puits
    POND = "POND"

    # Vegetation
    OPEN_LAND = "OPEN_LAND"
    ROUGH_OPEN = "ROUGH_OPEN"
    FOREST_GOOD = "FOREST_GOOD"
    SLOW_FOREST = "SLOW_FOREST"
    FIGHT = "FIGHT"                        # végétation impénétrable
    VEG_IMPASSABLE = "VEG_IMPASSABLE"
    ORCHARD = "ORCHARD"

    # Paths / roads
    ROAD_PAVED = "ROAD_PAVED"
    ROAD_UNPAVED = "ROAD_UNPAVED"
    ROAD_FOREST = "ROAD_FOREST"
    PATH = "PATH"
    FOOTPATH = "FOOTPATH"
    NARROW_RIDE = "NARROW_RIDE"
    BRIDGE = "BRIDGE"
    RAILROAD = "RAILROAD"
    CROSSING_POINT = "CROSSING_POINT"
    TUNNEL = "TUNNEL"

    # Man-made
    BUILDING = "BUILDING"
    SETTLEMENT = "SETTLEMENT"
    RUIN = "RUIN"
    PAVED_AREA = "PAVED_AREA"
    WALL = "WALL"
    WALL_RUINED = "WALL_RUINED"
    FENCE = "FENCE"
    HEDGE = "HEDGE"
    TOWER = "TOWER"
    PASSAGE = "PASSAGE"
    STAIRS = "STAIRS"
    POWERLINE = "POWERLINE"
    SPECIAL_MANMADE = "SPECIAL_MANMADE"

    # Layout & course elements → ignored
    NORTH_LINE = "NORTH_LINE"
    COURSE_START = "COURSE_START"
    COURSE_FINISH = "COURSE_FINISH"
    COURSE_CONTROL = "COURSE_CONTROL"
    COURSE_NUMBER = "COURSE_NUMBER"
    MAP_FRAME = "MAP_FRAME"
    TEXT_BLOCK = "TEXT_BLOCK"

    # Forbidden
    OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
    DANGEROUS_CROSSING = "DANGEROUS_CROSSING"

    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# SemanticInfo — résultat de la résolution d'un code symbole
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SemanticInfo:
    """
    Information sémantique complète pour un code symbole OCAD.

    Attributes:
        category:      Catégorie large (SemanticCategory).
        terrain_type:  Type précis (TerrainType).
        is_layout:     True → objet de mise en page, à ignorer dans tous les traitements.
        is_forbidden:  True → zone interdite ou infranchissable (barrière graph + raster).
        attractiveness: Score d'attractivité de base en tant que poste [0–1].
                        0 = pas un poste, 1 = poste idéal.
        readability:   Lisibilité de l'objet sur carte [0–1].
        base_td:       Niveau technique de base [1–5] (0 = pas un poste).
        description_fr: Libellé français pour les interfaces.
    """
    category: SemanticCategory
    terrain_type: TerrainType
    is_layout: bool = False
    is_forbidden: bool = False
    attractiveness: float = 0.0    # [0.0, 1.0]
    readability: float = 0.0       # [0.0, 1.0]
    base_td: int = 0               # 0 = pas un poste candidate
    description_fr: str = ""


# ---------------------------------------------------------------------------
# Table de correspondance principale
# Code OCAD (int) → SemanticInfo
# ---------------------------------------------------------------------------

_SYMBOL_TABLE: dict[int, SemanticInfo] = {

    # ---- COURBES DE NIVEAU (terrain info, pas candidats postes) ----
    101: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.CONTOUR,
                      description_fr="Courbe de niveau"),
    102: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.CONTOUR,
                      description_fr="Courbe maîtresse"),
    103: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.CONTOUR,
                      description_fr="Ligne de forme"),
    104: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.CONTOUR,
                      description_fr="Ligne de pente"),
    105: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.CONTOUR,
                      description_fr="Courbe (remplissage)"),

    # ---- RELIEF PONCTUEL — bons candidats ----
    106: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.EARTHWALL,
                      attractiveness=0.65, readability=0.7, base_td=3,
                      description_fr="Talus de terre"),
    107: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.EARTHWALL_RUIN,
                      attractiveness=0.50, readability=0.55, base_td=3,
                      description_fr="Talus de terre ruiné"),
    108: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.EROSION_GULLY,
                      attractiveness=0.60, readability=0.60, base_td=3,
                      description_fr="Ravine / fossé de terre"),
    109: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.EROSION_GULLY,
                      attractiveness=0.55, readability=0.55, base_td=4,
                      description_fr="Petite ravine"),
    110: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.KNOLL,
                      attractiveness=0.75, readability=0.80, base_td=2,
                      description_fr="Butte"),
    111: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.KNOLL,
                      attractiveness=0.80, readability=0.85, base_td=2,
                      description_fr="Petite butte"),
    112: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.SADDLE,
                      attractiveness=0.70, readability=0.75, base_td=3,
                      description_fr="Col / selle"),
    113: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.DEPRESSION,
                      attractiveness=0.85, readability=0.80, base_td=3,
                      description_fr="Dépression"),
    114: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.DEPRESSION,
                      attractiveness=0.80, readability=0.75, base_td=3,
                      description_fr="Petite dépression"),
    115: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.PIT,
                      attractiveness=0.85, readability=0.80, base_td=4,
                      description_fr="Fosse / trou"),
    116: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.BROKEN_GROUND,
                      attractiveness=0.40, readability=0.50, base_td=3,
                      description_fr="Terrain accidenté"),
    117: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.HILL_TOP,
                      attractiveness=0.70, readability=0.75, base_td=2,
                      description_fr="Accident de terrain proéminent"),

    # ---- FALAISES & ROCHERS ----
    201: SemanticInfo(SemanticCategory.ROCK, TerrainType.CLIFF_IMPASSABLE,
                      is_forbidden=True,
                      attractiveness=0.70, readability=0.90, base_td=3,
                      description_fr="Falaise infranchissable"),
    202: SemanticInfo(SemanticCategory.ROCK, TerrainType.CLIFF,
                      attractiveness=0.75, readability=0.85, base_td=3,
                      description_fr="Falaise"),
    203: SemanticInfo(SemanticCategory.ROCK, TerrainType.ROCKY_GROUND,
                      attractiveness=0.50, readability=0.60, base_td=3,
                      description_fr="Terrain rocheux"),
    204: SemanticInfo(SemanticCategory.ROCK, TerrainType.BOULDER,
                      attractiveness=0.90, readability=0.95, base_td=2,
                      description_fr="Bloc rocheux"),
    205: SemanticInfo(SemanticCategory.ROCK, TerrainType.BOULDER_CLUSTER,
                      attractiveness=0.80, readability=0.85, base_td=3,
                      description_fr="Amas de rochers"),
    206: SemanticInfo(SemanticCategory.ROCK, TerrainType.STONY_SLOW,
                      attractiveness=0.35, readability=0.50, base_td=3,
                      description_fr="Terrain pierreux (lent)"),
    207: SemanticInfo(SemanticCategory.ROCK, TerrainType.STONY_SLOW,
                      attractiveness=0.30, readability=0.45, base_td=4,
                      description_fr="Terrain pierreux (marche)"),
    208: SemanticInfo(SemanticCategory.ROCK, TerrainType.STONY_FIGHT,
                      attractiveness=0.20, readability=0.35, base_td=4,
                      description_fr="Terrain pierreux (lutte)"),
    209: SemanticInfo(SemanticCategory.ROCK, TerrainType.BARE_ROCK,
                      attractiveness=0.55, readability=0.65, base_td=2,
                      description_fr="Terrain sableux"),
    210: SemanticInfo(SemanticCategory.ROCK, TerrainType.BARE_ROCK,
                      attractiveness=0.60, readability=0.70, base_td=2,
                      description_fr="Roche nue"),
    211: SemanticInfo(SemanticCategory.LANDFORM, TerrainType.EROSION_GULLY,
                      attractiveness=0.65, readability=0.70, base_td=3,
                      description_fr="Tranchée"),

    # ---- VÉGÉTATION (zones, affectent mouvement) ----
    301: SemanticInfo(SemanticCategory.VEGETATION_EDGE, TerrainType.OPEN_LAND,
                      attractiveness=0.35, readability=0.65, base_td=1,
                      description_fr="Terrain ouvert"),
    302: SemanticInfo(SemanticCategory.VEGETATION_EDGE, TerrainType.OPEN_LAND,
                      attractiveness=0.30, readability=0.55, base_td=1,
                      description_fr="Terrain ouvert (arbres épars)"),
    303: SemanticInfo(SemanticCategory.VEGETATION_EDGE, TerrainType.ROUGH_OPEN,
                      attractiveness=0.30, readability=0.55, base_td=2,
                      description_fr="Terrain ouvert accidenté"),
    304: SemanticInfo(SemanticCategory.VEGETATION_EDGE, TerrainType.ROUGH_OPEN,
                      attractiveness=0.25, readability=0.45, base_td=2,
                      description_fr="Terrain ouvert accidenté (arbres épars)"),
    305: SemanticInfo(SemanticCategory.VEGETATION_EDGE, TerrainType.FOREST_GOOD,
                      attractiveness=0.20, readability=0.40, base_td=2,
                      description_fr="Forêt courante"),
    306: SemanticInfo(SemanticCategory.VEGETATION_EDGE, TerrainType.SLOW_FOREST,
                      attractiveness=0.15, readability=0.35, base_td=3,
                      description_fr="Végétation (lent)"),
    307: SemanticInfo(SemanticCategory.VEGETATION_EDGE, TerrainType.SLOW_FOREST,
                      attractiveness=0.10, readability=0.30, base_td=4,
                      description_fr="Végétation (marche)"),
    308: SemanticInfo(SemanticCategory.VEGETATION_EDGE, TerrainType.FIGHT,
                      attractiveness=0.05, readability=0.20, base_td=5,
                      description_fr="Végétation (lutte)"),
    309: SemanticInfo(SemanticCategory.FORBIDDEN, TerrainType.VEG_IMPASSABLE,
                      is_forbidden=True,
                      description_fr="Végétation infranchissable"),
    310: SemanticInfo(SemanticCategory.VEGETATION_EDGE, TerrainType.ORCHARD,
                      attractiveness=0.25, readability=0.50, base_td=2,
                      description_fr="Verger"),
    311: SemanticInfo(SemanticCategory.VEGETATION_EDGE, TerrainType.ORCHARD,
                      attractiveness=0.20, readability=0.45, base_td=2,
                      description_fr="Vigne"),

    # ---- EAU ----
    401: SemanticInfo(SemanticCategory.WATER, TerrainType.OPEN_WATER,
                      is_forbidden=True,
                      attractiveness=0.60, readability=0.90, base_td=2,
                      description_fr="Plan d'eau"),
    402: SemanticInfo(SemanticCategory.FORBIDDEN, TerrainType.STREAM_IMPASSABLE,
                      is_forbidden=True,
                      description_fr="Plan d'eau infranchissable"),
    403: SemanticInfo(SemanticCategory.WATER, TerrainType.STREAM,
                      attractiveness=0.60, readability=0.70, base_td=2,
                      description_fr="Cours d'eau franchissable"),
    404: SemanticInfo(SemanticCategory.FORBIDDEN, TerrainType.STREAM_IMPASSABLE,
                      is_forbidden=True,
                      description_fr="Cours d'eau infranchissable"),
    405: SemanticInfo(SemanticCategory.WATER, TerrainType.STREAM,
                      attractiveness=0.55, readability=0.65, base_td=2,
                      description_fr="Cours d'eau temporaire"),
    406: SemanticInfo(SemanticCategory.FORBIDDEN, TerrainType.STREAM_IMPASSABLE,
                      is_forbidden=True,
                      description_fr="Cours d'eau infranchissable (bis)"),
    407: SemanticInfo(SemanticCategory.WATER, TerrainType.STREAM,
                      attractiveness=0.50, readability=0.60, base_td=3,
                      description_fr="Petit cours d'eau"),
    408: SemanticInfo(SemanticCategory.WATER, TerrainType.MARSH,
                      attractiveness=0.55, readability=0.70, base_td=3,
                      description_fr="Marécage étroit"),
    409: SemanticInfo(SemanticCategory.WATER, TerrainType.MARSH,
                      attractiveness=0.60, readability=0.75, base_td=3,
                      description_fr="Marécage"),
    410: SemanticInfo(SemanticCategory.FORBIDDEN, TerrainType.MARSH_IMPASSABLE,
                      is_forbidden=True,
                      description_fr="Marécage infranchissable"),
    411: SemanticInfo(SemanticCategory.WATER, TerrainType.MARSH,
                      attractiveness=0.45, readability=0.55, base_td=4,
                      description_fr="Marécage indistinct"),
    412: SemanticInfo(SemanticCategory.WATER, TerrainType.SPRING,
                      attractiveness=0.75, readability=0.80, base_td=2,
                      description_fr="Puits / source"),
    413: SemanticInfo(SemanticCategory.WATER, TerrainType.STREAM,
                      attractiveness=0.50, readability=0.60, base_td=3,
                      description_fr="Cours d'eau (buse)"),

    # ---- CHEMINS & ROUTES ----
    501: SemanticInfo(SemanticCategory.PATH, TerrainType.ROAD_PAVED,
                      attractiveness=0.40, readability=0.80, base_td=1,
                      description_fr="Route goudronnée"),
    502: SemanticInfo(SemanticCategory.PATH, TerrainType.ROAD_UNPAVED,
                      attractiveness=0.45, readability=0.75, base_td=1,
                      description_fr="Route non goudronnée"),
    503: SemanticInfo(SemanticCategory.PATH, TerrainType.ROAD_FOREST,
                      attractiveness=0.50, readability=0.70, base_td=1,
                      description_fr="Chemin forestier"),
    504: SemanticInfo(SemanticCategory.PATH, TerrainType.PATH,
                      attractiveness=0.55, readability=0.70, base_td=2,
                      description_fr="Sentier"),
    505: SemanticInfo(SemanticCategory.PATH, TerrainType.FOOTPATH,
                      attractiveness=0.55, readability=0.70, base_td=2,
                      description_fr="Sentier piéton"),
    506: SemanticInfo(SemanticCategory.PATH, TerrainType.NARROW_RIDE,
                      attractiveness=0.50, readability=0.60, base_td=3,
                      description_fr="Layon / coupe forestière"),
    507: SemanticInfo(SemanticCategory.MANMADE, TerrainType.POWERLINE,
                      attractiveness=0.30, readability=0.65, base_td=2,
                      description_fr="Ligne électrique"),
    508: SemanticInfo(SemanticCategory.PATH, TerrainType.BRIDGE,
                      attractiveness=0.70, readability=0.85, base_td=2,
                      description_fr="Pont"),
    509: SemanticInfo(SemanticCategory.PATH, TerrainType.CROSSING_POINT,
                      attractiveness=0.55, readability=0.70, base_td=2,
                      description_fr="Passage à niveau"),
    510: SemanticInfo(SemanticCategory.PATH, TerrainType.RAILROAD,
                      is_forbidden=True,
                      description_fr="Voie ferrée"),
    511: SemanticInfo(SemanticCategory.MANMADE, TerrainType.POWERLINE,
                      attractiveness=0.25, readability=0.60, base_td=2,
                      description_fr="Ligne électrique principale"),
    512: SemanticInfo(SemanticCategory.MANMADE, TerrainType.POWERLINE,
                      attractiveness=0.25, readability=0.60, base_td=2,
                      description_fr="Très haute tension"),
    513: SemanticInfo(SemanticCategory.PATH, TerrainType.TUNNEL,
                      attractiveness=0.60, readability=0.75, base_td=2,
                      description_fr="Tunnel / passage souterrain"),
    514: SemanticInfo(SemanticCategory.MANMADE, TerrainType.WALL,
                      attractiveness=0.65, readability=0.80, base_td=2,
                      description_fr="Mur de pierres"),
    515: SemanticInfo(SemanticCategory.MANMADE, TerrainType.FENCE,
                      attractiveness=0.55, readability=0.70, base_td=2,
                      description_fr="Clôture"),
    516: SemanticInfo(SemanticCategory.PATH, TerrainType.CROSSING_POINT,
                      attractiveness=0.60, readability=0.75, base_td=2,
                      description_fr="Point de franchissement"),
    517: SemanticInfo(SemanticCategory.MANMADE, TerrainType.PASSAGE,
                      attractiveness=0.85, readability=0.90, base_td=2,
                      description_fr="Passage étroit"),
    518: SemanticInfo(SemanticCategory.MANMADE, TerrainType.HEDGE,
                      attractiveness=0.55, readability=0.70, base_td=2,
                      description_fr="Haie"),
    519: SemanticInfo(SemanticCategory.MANMADE, TerrainType.WALL_RUINED,
                      attractiveness=0.50, readability=0.60, base_td=3,
                      description_fr="Mur en ruine"),
    521: SemanticInfo(SemanticCategory.MANMADE, TerrainType.BUILDING,
                      is_forbidden=True,
                      attractiveness=0.80, readability=0.95, base_td=2,
                      description_fr="Bâtiment"),
    522: SemanticInfo(SemanticCategory.MANMADE, TerrainType.SETTLEMENT,
                      is_forbidden=True,
                      attractiveness=0.40, readability=0.70, base_td=2,
                      description_fr="Zone construite"),
    523: SemanticInfo(SemanticCategory.MANMADE, TerrainType.PAVED_AREA,
                      attractiveness=0.50, readability=0.75, base_td=2,
                      description_fr="Zone pavée"),
    524: SemanticInfo(SemanticCategory.MANMADE, TerrainType.SPECIAL_MANMADE,
                      description_fr="Zone spéciale"),
    525: SemanticInfo(SemanticCategory.MANMADE, TerrainType.RUIN,
                      attractiveness=0.70, readability=0.80, base_td=2,
                      description_fr="Ruine"),
    526: SemanticInfo(SemanticCategory.MANMADE, TerrainType.TOWER,
                      attractiveness=0.75, readability=0.90, base_td=1,
                      description_fr="Grande tour"),
    527: SemanticInfo(SemanticCategory.MANMADE, TerrainType.TOWER,
                      attractiveness=0.70, readability=0.85, base_td=1,
                      description_fr="Petite tour"),
    528: SemanticInfo(SemanticCategory.MANMADE, TerrainType.SPECIAL_MANMADE,
                      attractiveness=0.50, readability=0.65, base_td=2,
                      description_fr="Râtelier à fourrage"),
    529: SemanticInfo(SemanticCategory.MANMADE, TerrainType.SPECIAL_MANMADE,
                      attractiveness=0.55, readability=0.70, base_td=2,
                      description_fr="Objet artificiel spécial (ponctuel)"),
    # Escaliers (ISSprOM 531 ou variantes)
    531: SemanticInfo(SemanticCategory.MANMADE, TerrainType.STAIRS,
                      attractiveness=0.80, readability=0.90, base_td=2,
                      description_fr="Escaliers"),

    # ---- MISE EN PAGE (TOUJOURS IGNORÉS) ----
    601: SemanticInfo(SemanticCategory.LAYOUT, TerrainType.NORTH_LINE,
                      is_layout=True, description_fr="Ligne nord magnétique"),
    602: SemanticInfo(SemanticCategory.LAYOUT, TerrainType.NORTH_LINE,
                      is_layout=True, description_fr="Réseau de nord"),
    603: SemanticInfo(SemanticCategory.LAYOUT, TerrainType.NORTH_LINE,
                      is_layout=True, description_fr="Point nord magnétique"),

    # ---- ÉLÉMENTS DE TRACÉ (IGNORÉS comme candidats) ----
    701: SemanticInfo(SemanticCategory.COURSE, TerrainType.COURSE_START,
                      is_layout=True, description_fr="Départ"),
    702: SemanticInfo(SemanticCategory.COURSE, TerrainType.COURSE_CONTROL,
                      is_layout=True, description_fr="Point de départ"),
    703: SemanticInfo(SemanticCategory.COURSE, TerrainType.COURSE_CONTROL,
                      is_layout=True, description_fr="Poste"),
    704: SemanticInfo(SemanticCategory.LAYOUT, TerrainType.COURSE_NUMBER,
                      is_layout=True, description_fr="Numéro de poste"),
    705: SemanticInfo(SemanticCategory.COURSE, TerrainType.COURSE_FINISH,
                      is_layout=True, description_fr="Arrivée"),
    706: SemanticInfo(SemanticCategory.COURSE, TerrainType.CROSSING_POINT,
                      is_layout=True, description_fr="Point de passage obligé"),
    707: SemanticInfo(SemanticCategory.FORBIDDEN, TerrainType.OUT_OF_BOUNDS,
                      is_forbidden=True,
                      description_fr="Zone hors-limites"),
    708: SemanticInfo(SemanticCategory.FORBIDDEN, TerrainType.DANGEROUS_CROSSING,
                      is_forbidden=True,
                      description_fr="Croisement dangereux"),
    709: SemanticInfo(SemanticCategory.COURSE, TerrainType.SPECIAL_MANMADE,
                      is_layout=True, description_fr="Poste de premiers secours"),
    710: SemanticInfo(SemanticCategory.COURSE, TerrainType.SPECIAL_MANMADE,
                      is_layout=True, description_fr="Ravitaillement"),
    711: SemanticInfo(SemanticCategory.COURSE, TerrainType.CROSSING_POINT,
                      is_layout=True, description_fr="Franchissement obligatoire"),
    712: SemanticInfo(SemanticCategory.COURSE, TerrainType.CROSSING_POINT,
                      is_layout=True, description_fr="Couloir obligatoire"),
    713: SemanticInfo(SemanticCategory.LAYOUT, TerrainType.MAP_FRAME,
                      is_layout=True, description_fr="Marque de recalage"),
}

# Fallback pour codes inconnus
_UNKNOWN_INFO = SemanticInfo(
    SemanticCategory.UNKNOWN, TerrainType.UNKNOWN,
    description_fr="Symbole inconnu",
)


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def get_semantic_info(ocad_sym: int | float) -> SemanticInfo:
    """Retourne l'info sémantique pour un code symbole OCAD.

    Accepte un float (ex : 204.0) ou un int (204).
    Les suffixes décimaux standard (ex : .1, .2) sont ignorés — le code
    de base est utilisé.

    Returns:
        SemanticInfo correspondant, ou un objet UNKNOWN si non référencé.
    """
    code = int(ocad_sym)
    return _SYMBOL_TABLE.get(code, _UNKNOWN_INFO)


def is_layout(ocad_sym: int | float) -> bool:
    """True si le symbole est un élément de mise en page (à ignorer)."""
    return get_semantic_info(ocad_sym).is_layout


def is_forbidden(ocad_sym: int | float) -> bool:
    """True si le symbole représente une zone interdite / infranchissable."""
    return get_semantic_info(ocad_sym).is_forbidden


def allowed_sym_codes_for_category(category: SemanticCategory) -> list[int]:
    """Liste de tous les codes OCAD appartenant à une SemanticCategory donnée."""
    return [code for code, info in _SYMBOL_TABLE.items()
            if info.category == category]
