"""
RouteAnalyzer — Équivalent OCAD Route Analyzer pour CO sprint.

Construit un graphe NetworkX depuis les ways OSM (piétonnes) et utilise A*
pour calculer la route optimale entre deux postes WGS84. Sert à :
  - Détecter les dog-legs RÉELS (C01) : si A*(P_n-1 → P_n+1) passe à
    moins de dog_leg_proximity_m du P_n, c'est un dog-leg.
  - Évaluer le choix d'itinéraire (C11) : Yen's k-shortest → score Jaccard
    de diversité [0.0 = couloir unique, 1.0 = vraies options].

Sources :
  OCAD Route Analyzer (ocad.com/wiki/…/Route_Analyzer)
  IOF Sprint Course Planning Guidelines Jun 2020 §4.3
"""

import math
from typing import List, Tuple, Optional

try:
    import networkx as nx
    _HAS_NX = True
except ImportError:
    _HAS_NX = False


# ── Géométrie de base ──────────────────────────────────────────────────────────

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ── RouteAnalyzer ──────────────────────────────────────────────────────────────

class RouteAnalyzer:
    """
    Graphe de rues OSM + A* pour route réelle entre deux postes.

    highway_ways : liste de ways, chaque way = liste de (lng, lat).
    """

    def __init__(self, highway_ways: List[List[Tuple[float, float]]]):
        if not _HAS_NX:
            raise ImportError("networkx requis pour RouteAnalyzer")
        self.graph = self._build_graph(highway_ways)
        self._nodes: List[Tuple[float, float]] = list(self.graph.nodes())
        self._route_cache: dict = {}
        self._parallel_path_cache: dict = {}
        self._line_crossing_cache: dict = {}
        self._cache_stats: dict = {"hits": 0, "misses": 0, "total_time_ms": 0.0}

    # ── Construction du graphe ─────────────────────────────────────────────────

    def _build_graph(self, ways: List[List[Tuple[float, float]]]) -> "nx.Graph":
        G = nx.Graph()
        for way in ways:
            if len(way) < 2:
                continue
            # Arrondir à 6 décimales (~0.1m) pour fusionner les noeuds identiques
            nodes = [(round(lng, 6), round(lat, 6)) for lng, lat in way]
            for i in range(len(nodes) - 1):
                n1, n2 = nodes[i], nodes[i + 1]
                if n1 == n2:
                    continue
                dist = _haversine_m(n1[1], n1[0], n2[1], n2[0])
                if dist == 0:
                    continue
                if G.has_edge(n1, n2):
                    if G[n1][n2]["weight"] > dist:
                        G[n1][n2]["weight"] = dist
                else:
                    G.add_edge(n1, n2, weight=dist)
        return G

    # ── Nœud le plus proche ───────────────────────────────────────────────────

    def _nearest_node(self, lng: float, lat: float) -> Optional[Tuple[float, float]]:
        if not self._nodes:
            return None
        # Approximation rapide (degrés² suffisants pour un voisinage local)
        return min(self._nodes, key=lambda n: (n[0] - lng) ** 2 + (n[1] - lat) ** 2)

    # ── A* route optimale ──────────────────────────────────────────────────────

    def find_optimal_route(
        self,
        start_lng: float, start_lat: float,
        end_lng: float, end_lat: float,
    ) -> Optional[List[Tuple[float, float]]]:
        """
        Retourne la liste de nœuds (lng, lat) du chemin optimal, ou None.
        """
        n_start = self._nearest_node(start_lng, start_lat)
        n_end = self._nearest_node(end_lng, end_lat)
        if n_start is None or n_end is None or n_start == n_end:
            return None
        try:
            def heuristic(a, b):
                return _haversine_m(a[1], a[0], b[1], b[0])
            path = nx.astar_path(self.graph, n_start, n_end, heuristic=heuristic, weight="weight")
            return path
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    # ── Détection dog-leg réel ─────────────────────────────────────────────────

    def detect_dogleg(
        self,
        c_prev: dict,
        c_mid: dict,
        c_next: dict,
        proximity_m: float = 30.0,
    ) -> Tuple[bool, float]:
        """
        Dog-leg réel : le chemin optimal P_prev → P_next passe à moins de
        proximity_m du P_mid (le coureur "voit" le poste sans le chercher).

        Retourne (is_dogleg: bool, min_dist_m: float).
        """
        path = self.find_optimal_route(
            c_prev["lng"], c_prev["lat"],
            c_next["lng"], c_next["lat"],
        )
        if path is None or len(path) < 2:
            return False, float("inf")

        min_dist = min(
            _haversine_m(c_mid["lat"], c_mid["lng"], node[1], node[0])
            for node in path
        )
        return min_dist < proximity_m, min_dist

    # ── Cache k-shortest paths ─────────────────────────────────────────────────

    def _k_shortest_cached(
        self,
        n_start: tuple,
        n_end: tuple,
        k: int,
        timeout_ms: int = 200,
    ) -> list:
        """k-shortest paths avec cache (n_start, n_end, k) et timeout."""
        import time as _t
        key = (n_start, n_end, k)
        if key in self._route_cache:
            self._cache_stats["hits"] += 1
            return self._route_cache[key]
        self._cache_stats["misses"] += 1
        t0 = _t.time()
        try:
            gen = nx.shortest_simple_paths(self.graph, n_start, n_end, weight="weight")
            paths = []
            for p in gen:
                if (_t.time() - t0) * 1000 > timeout_ms:
                    break
                paths.append(p)
                if len(paths) >= k:
                    break
        except (nx.NetworkXNoPath, nx.NodeNotFound, nx.NetworkXError):
            paths = []
        self._cache_stats["total_time_ms"] += (_t.time() - t0) * 1000
        self._route_cache[key] = paths
        return paths

    def get_cache_stats(self) -> dict:
        """Métriques de performance du cache k-shortest (pour monitoring GA)."""
        hits = self._cache_stats["hits"]
        misses = self._cache_stats["misses"]
        total = max(1, hits + misses)
        return {
            "hit_rate": round(hits / total, 3),
            "total_calls": total,
            "avg_time_ms": round(self._cache_stats["total_time_ms"] / max(1, misses), 1),
        }

    # ── Points de décision ────────────────────────────────────────────────────

    def count_decision_points(
        self,
        start_lng: float, start_lat: float,
        end_lng: float, end_lat: float,
    ) -> int:
        """
        Bifurcations significatives sur le chemin A* entre deux postes.

        Un nœud est une bifurcation significative s'il a degré ≥ 3 ET qu'au
        moins une branche alternative (hors direction d'origine et de destination)
        diverge de plus de 30° de la direction principale du chemin.
        Exclut la direction arrière pour éviter les faux positifs sur jonctions
        en ligne droite avec un léger embranchement.
        """
        route = self.find_optimal_route(start_lng, start_lat, end_lng, end_lat)
        if not route or len(route) < 2:
            return 0
        count = 0
        for idx in range(1, len(route) - 1):
            node = route[idx]
            if self.graph.degree(node) < 3:
                continue
            if self._has_significant_alternative(node, route[idx - 1], route[idx + 1]):
                count += 1
        return count

    def get_decision_point_coords(
        self,
        start_lng: float, start_lat: float,
        end_lng: float, end_lat: float,
    ) -> List[dict]:
        """Retourne la liste {lng, lat} des points de décision sur le chemin A*."""
        route = self.find_optimal_route(start_lng, start_lat, end_lng, end_lat)
        if not route or len(route) < 3:
            return []
        result = []
        for idx in range(1, len(route) - 1):
            node = route[idx]
            if self.graph.degree(node) >= 3 and self._has_significant_alternative(
                node, route[idx - 1], route[idx + 1]
            ):
                result.append({"lng": node[0], "lat": node[1]})
        return result

    def _has_significant_alternative(
        self, node: tuple, prev_node: tuple, next_node: tuple
    ) -> bool:
        """
        True si node a un voisin alternatif (hors prev/next) déviant de >30°
        de la direction principale prev→node→next.
        """
        cos_lat = math.cos(math.radians(node[1]))
        dx_main = (next_node[0] - node[0]) * 111_000 * cos_lat
        dy_main = (next_node[1] - node[1]) * 111_000
        mag_main = math.sqrt(dx_main ** 2 + dy_main ** 2)
        if mag_main == 0:
            return False
        ux, uy = dx_main / mag_main, dy_main / mag_main
        for nb in self.graph.neighbors(node):
            if nb == prev_node or nb == next_node:
                continue
            dx = (nb[0] - node[0]) * 111_000 * cos_lat
            dy = (nb[1] - node[1]) * 111_000
            mag = math.sqrt(dx ** 2 + dy ** 2)
            if mag == 0:
                continue
            dot = max(-1.0, min(1.0, ux * dx / mag + uy * dy / mag))
            if math.degrees(math.acos(dot)) > 30:
                return True
        return False

    def _is_significant_fork(self, node: tuple) -> bool:
        """True si au moins 2 branches du nœud divergent de >30° (sans contexte chemin).
        Préférer _has_significant_alternative() quand le chemin A* est connu.
        """
        neighbors = list(self.graph.neighbors(node))
        if len(neighbors) < 3:
            return False
        cos_lat = math.cos(math.radians(node[1]))
        vecs = []
        for nb in neighbors:
            dx = (nb[0] - node[0]) * 111_000 * cos_lat
            dy = (nb[1] - node[1]) * 111_000
            mag = math.sqrt(dx * dx + dy * dy)
            if mag > 0:
                vecs.append((dx / mag, dy / mag))
        for i in range(len(vecs)):
            for j in range(i + 1, len(vecs)):
                dot = max(-1.0, min(1.0, vecs[i][0] * vecs[j][0] + vecs[i][1] * vecs[j][1]))
                if math.degrees(math.acos(dot)) > 30:
                    return True
        return False

    # ── Score de diversité d'itinéraire ───────────────────────────────────────

    def route_diversity_info(
        self,
        start_lng: float, start_lat: float,
        end_lng: float, end_lat: float,
        k: int = 3,
        timeout_ms: int = 200,
    ) -> dict:
        """
        Score Jaccard + nombre de routes crédibles (ratio longueur 0.85–1.30).

        Retourne {"jaccard": float, "credible_routes": int}.
        Les routes trop longues (> 30% de l'optimale) ou trop courtes (< 85%)
        sont écartées car non crédibles pour un orienteur.
        """
        n_start = self._nearest_node(start_lng, start_lat)
        n_end = self._nearest_node(end_lng, end_lat)
        if n_start is None or n_end is None or n_start == n_end:
            return {"jaccard": 0.0, "credible_routes": 0}
        paths = self._k_shortest_cached(n_start, n_end, k, timeout_ms)
        if not paths:
            return {"jaccard": 0.0, "credible_routes": 0}
        optimal_len = self.route_length_m(paths[0])
        credible = [
            p for p in paths
            if optimal_len == 0
            or 0.85 <= self.route_length_m(p) / optimal_len <= 1.30
        ]
        jaccard = self._jaccard_from_routes(credible) if len(credible) >= 2 else 0.0

        # similarity_ratio : min_dist / max_dist parmi les routes crédibles.
        # Proche de 1.0 = les deux itinéraires semblent de longueur identique
        # → dilemme gauche/droite visuellement ambigu (sprint). Coût nul : longueurs
        # déjà calculées pour le filtre credible ci-dessus.
        if len(credible) >= 2:
            lengths = [self.route_length_m(p) for p in credible]
            min_l, max_l = min(lengths), max(lengths)
            similarity_ratio = round(min_l / max_l, 4) if max_l > 0 else 1.0
        else:
            similarity_ratio = 0.0

        return {
            "jaccard": round(jaccard, 4),
            "credible_routes": len(credible),
            "similarity_ratio": similarity_ratio,
        }

    def route_diversity_score(
        self,
        start_lng: float, start_lat: float,
        end_lng: float, end_lat: float,
        k: int = 3,
    ) -> float:
        """
        Score Jaccard de diversité entre les k meilleures routes [0.0, 1.0].
        0.0 = couloir unique, 1.0 = vraies alternatives distinctes.
        Utilise le cache interne pour performance GA.
        """
        return self.route_diversity_info(start_lng, start_lat, end_lng, end_lat, k)["jaccard"]

    # ── Saut de ligne ─────────────────────────────────────────────────────────

    @staticmethod
    def _segment_cross_t(
        ax: float, ay: float, bx: float, by: float,
        px: float, py: float, qx: float, qy: float,
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Intersection stricte des segments AB et PQ en coordonnées Cartésiennes.

        Retourne (t, s) si les segments se croisent strictement (0 < t,s < 1),
        sinon (None, None).  t = position sur AB, s = position sur PQ.
        """
        d1x, d1y = bx - ax, by - ay
        d2x, d2y = qx - px, qy - py
        denom = d1x * d2y - d1y * d2x
        if abs(denom) < 1e-10:
            return None, None
        dx, dy = px - ax, py - ay
        t = (dx * d2y - dy * d2x) / denom
        s = (dx * d1y - dy * d1x) / denom
        if 0.0 < t < 1.0 and 0.0 < s < 1.0:
            return t, s
        return None, None

    def score_line_crossing(
        self,
        start_lng: float, start_lat: float,
        end_lng: float, end_lat: float,
        min_leg_m: float = 150.0,
    ) -> float:
        """
        Score ∈ [0, 1] : qualité des sauts de ligne sur l'interposte (forêt).

        Détecte les arêtes OSM qui CROISENT la jambe à angle significatif
        (> 50° de la direction de la jambe) — technique de navigation où le
        franchissement d'un sentier/lisière/clôture confirme la position du
        coureur en cours de jambe.

        Distinct du Terme K (main courante = arête PARALLÈLE).
        Forêt MD/LD uniquement ; cache par paire de postes.
        """
        cache_key = (
            round(start_lng, 4), round(start_lat, 4),
            round(end_lng, 4), round(end_lat, 4),
        )
        if cache_key in self._line_crossing_cache:
            return self._line_crossing_cache[cache_key]
        result = self._compute_line_crossing_score(
            start_lng, start_lat, end_lng, end_lat, min_leg_m
        )
        self._line_crossing_cache[cache_key] = result
        return result

    def _compute_line_crossing_score(
        self,
        start_lng: float, start_lat: float,
        end_lng: float, end_lat: float,
        min_leg_m: float,
    ) -> float:
        """Calcul effectif du score saut de ligne."""
        cos_lat = math.cos(math.radians((start_lat + end_lat) / 2))
        k_lng = 111_000 * cos_lat
        k_lat = 111_000

        ax, ay = start_lng * k_lng, start_lat * k_lat
        bx, by = end_lng * k_lng, end_lat * k_lat
        leg_m = math.sqrt((bx - ax) ** 2 + (by - ay) ** 2)

        if leg_m < min_leg_m:
            return 0.0

        # Vecteur jambe normé — pour calculer l'angle d'intersection
        ux, uy = (bx - ax) / leg_m, (by - ay) / leg_m

        total_quality = 0.0

        for n1, n2 in self.graph.edges():
            px, py = n1[0] * k_lng, n1[1] * k_lat
            qx, qy = n2[0] * k_lng, n2[1] * k_lat

            # Test d'intersection stricte segment jambe ∩ segment arête
            t, s = self._segment_cross_t(ax, ay, bx, by, px, py, qx, qy)
            if t is None:
                continue

            # Position le long de la jambe : doit être dans le corps [0.10, 0.90]
            # (pas à l'arrivée ni au départ — la feature serait attack/catch)
            if t < 0.10 or t > 0.90:
                continue

            # Angle de croisement : doit être > 50° (cos < 0.64)
            # Distingue saut de ligne (perpendiculaire) de main courante (parallèle)
            ex, ey = qx - px, qy - py
            edge_len = math.sqrt(ex * ex + ey * ey)
            if edge_len < 5.0:
                continue
            cos_angle = abs((ex * ux + ey * uy) / edge_len)
            if cos_angle >= 0.64:  # trop parallèle → c'est une main courante, pas un saut
                continue

            # Qualité de position : maximale au milieu de la jambe
            position_quality = 1.0 - 2.0 * abs(t - 0.5)  # ∈ [0, 1]

            # Qualité d'angle : meilleur quand perpendiculaire (cos_angle → 0)
            angle_quality = (0.64 - cos_angle) / 0.64  # ∈ [0, 1]

            crossing_quality = position_quality * angle_quality
            total_quality += crossing_quality

            if total_quality >= 0.80:  # arrêt anticipé : score déjà excellent
                break

        # Normalisation : 0.80 de score brut → score retourné = 1.0
        # (2 bons croisements × ~0.4 chacun ≈ 1.0)
        return min(1.0, total_quality / 0.80)

    def score_parallel_path_choice(
        self,
        start_lng: float, start_lat: float,
        end_lng: float, end_lat: float,
        min_leg_m: float = 200.0,
    ) -> float:
        """
        Score ∈ [0, 1] : qualité du choix d'itinéraire "tout droit vs chemin longeant".

        Détecte si un chemin OSM longe l'interposte forêt — même côté, même direction,
        offset latéral créant un vrai dilemme tactique (détour crédible mais pas trivial).

        Distinct du Terme E (Jaccard k-routes A→B) : ici le chemin NE relie PAS A à B,
        il longe la jambe sans la connecter. Forêt MD/LD uniquement.

        Cache par paire (start, end) arrondie à 4 décimales (~11m) pour performance GA.
        """
        cache_key = (
            round(start_lng, 4), round(start_lat, 4),
            round(end_lng, 4), round(end_lat, 4),
        )
        if cache_key in self._parallel_path_cache:
            return self._parallel_path_cache[cache_key]

        result = self._compute_parallel_path_score(
            start_lng, start_lat, end_lng, end_lat, min_leg_m
        )
        self._parallel_path_cache[cache_key] = result
        return result

    def _compute_parallel_path_score(
        self,
        start_lng: float, start_lat: float,
        end_lng: float, end_lat: float,
        min_leg_m: float,
    ) -> float:
        """Calcul effectif du score chemin parallèle (appelé une seule fois par paire).

        Agrège la couverture de TOUTES les arêtes qualifiantes d'un même côté via
        l'union des intervalles t-projetés sur [0, 1]. Gère correctement les chemins
        OSM fragmentés (nombreuses arêtes courtes de 20-100m).
        """
        cos_lat = math.cos(math.radians((start_lat + end_lat) / 2))
        k_lng = 111_000 * cos_lat
        k_lat = 111_000

        ax, ay = start_lng * k_lng, start_lat * k_lat
        bx, by = end_lng * k_lng, end_lat * k_lat
        leg_m = math.sqrt((bx - ax) ** 2 + (by - ay) ** 2)

        if leg_m < min_leg_m:
            return 0.0

        ux, uy = (bx - ax) / leg_m, (by - ay) / leg_m  # vecteur jambe normé
        px, py = -uy, ux                                 # perpendiculaire (gauche)

        # Buffers latéraux adaptatifs : 7 %–30 % de la longueur jambe
        buf_min = max(30.0, 0.07 * leg_m)
        buf_max = min(400.0, 0.30 * leg_m)

        # Collecter les arêtes qualifiantes côté gauche (perp > 0) et droite (perp < 0)
        # Chaque entrée : (t_lo, t_hi, avg_lat_m)
        left_segs: list = []
        right_segs: list = []

        for n1, n2 in self.graph.edges():
            nx1, ny1 = n1[0] * k_lng, n1[1] * k_lat
            nx2, ny2 = n2[0] * k_lng, n2[1] * k_lat

            # Direction : l'arête doit être dans ≤ 50° de la direction de la jambe
            ex, ey = nx2 - nx1, ny2 - ny1
            edge_len = math.sqrt(ex * ex + ey * ey)
            if edge_len < 5.0:
                continue
            cos_angle = abs((ex * ux + ey * uy) / edge_len)
            if cos_angle < 0.64:
                continue

            # Projection sur axe jambe
            t1 = ((nx1 - ax) * ux + (ny1 - ay) * uy) / leg_m
            t2 = ((nx2 - ax) * ux + (ny2 - ay) * uy) / leg_m
            t_lo_raw, t_hi_raw = min(t1, t2), max(t1, t2)

            # L'arête doit avoir une projection qui chevauche [0, 1]
            t_lo = max(0.0, t_lo_raw)
            t_hi = min(1.0, t_hi_raw)
            if t_hi - t_lo < 0.04:  # seuil bas : 4 % de jambe (ex. 24m sur 600m)
                continue

            # Projection sur axe perpendiculaire
            perp1 = (nx1 - ax) * px + (ny1 - ay) * py
            perp2 = (nx2 - ax) * px + (ny2 - ay) * py

            abs_p1, abs_p2 = abs(perp1), abs(perp2)
            avg_lat = (abs_p1 + abs_p2) / 2

            # Au moins une extrémité dans le buffer latéral (l'autre peut être dehors
            # si le chemin s'éloigne progressivement — tolérance en entrée/sortie)
            if avg_lat < buf_min or avg_lat > buf_max:
                continue
            if perp1 * perp2 < 0:  # côtés opposés → chemin traversant, pas longeant
                continue

            seg = (t_lo, t_hi, avg_lat)
            if perp1 >= 0:
                left_segs.append(seg)
            else:
                right_segs.append(seg)

        def _score_side(segs: list) -> float:
            if not segs:
                return 0.0
            # Union des intervalles t sur [0, 1]
            intervals = sorted((s[0], s[1]) for s in segs)
            merged = []
            cur_lo, cur_hi = intervals[0]
            for lo, hi in intervals[1:]:
                if lo <= cur_hi:
                    cur_hi = max(cur_hi, hi)
                else:
                    merged.append((cur_lo, cur_hi))
                    cur_lo, cur_hi = lo, hi
            merged.append((cur_lo, cur_hi))
            coverage = sum(hi - lo for lo, hi in merged)

            # Offset latéral moyen pondéré par la longueur de chaque segment qualifiant
            total_span = sum(s[1] - s[0] for s in segs)
            avg_lat_m = sum(s[2] * (s[1] - s[0]) for s in segs) / max(total_span, 1e-6)

            # Ratio de détour : aller-retour au chemin / longueur jambe
            detour_ratio = 2.0 * avg_lat_m / leg_m
            # Gaussienne centrée sur 18 % de détour idéal (σ = 0.15)
            balance = math.exp(-((detour_ratio - 0.18) ** 2) / (2 * 0.15 ** 2))

            return coverage * balance

        best_score = max(_score_side(left_segs), _score_side(right_segs))
        # Normalisation : score brut ≥ 0.40 → score retourné = 1.0
        return min(1.0, best_score / 0.40)

    # ── Infos graphe ───────────────────────────────────────────────────────────

    # ── k meilleures routes (Yen) ──────────────────────────────────────────────

    def get_k_routes(
        self,
        start_lng: float, start_lat: float,
        end_lng: float, end_lat: float,
        k: int = 3,
    ) -> List[List[Tuple[float, float]]]:
        """
        Retourne les k meilleures routes (Yen's algorithm via NetworkX).
        Chaque route = liste de (lng, lat). Utilise le cache interne.
        """
        n_start = self._nearest_node(start_lng, start_lat)
        n_end = self._nearest_node(end_lng, end_lat)
        if n_start is None or n_end is None or n_start == n_end:
            return []
        return self._k_shortest_cached(n_start, n_end, k)

    def route_length_m(self, route: List[Tuple[float, float]]) -> float:
        """Longueur totale d'une route (liste de (lng, lat)) en mètres."""
        total = 0.0
        for i in range(len(route) - 1):
            total += _haversine_m(route[i][1], route[i][0], route[i + 1][1], route[i + 1][0])
        return total

    def _jaccard_from_routes(self, routes: list) -> float:
        """Diversité Jaccard depuis des routes déjà calculées (zéro appel nx supplémentaire)."""
        if len(routes) < 2:
            return 0.0
        def _edge_set(p):
            return frozenset(frozenset([p[i], p[i + 1]]) for i in range(len(p) - 1))
        edge_sets = [_edge_set(p) for p in routes]
        divs = []
        for i in range(len(edge_sets)):
            for j in range(i + 1, len(edge_sets)):
                union = len(edge_sets[i] | edge_sets[j])
                inter = len(edge_sets[i] & edge_sets[j])
                if union > 0:
                    divs.append(1.0 - inter / union)
        return sum(divs) / len(divs) if divs else 0.0

    def score_circuit_choices(
        self,
        controls: list,
        k: int = 2,
        t_deadline: float = None,
    ) -> dict:
        """
        Score de choix d'itinéraire pour un circuit complet (post-GA uniquement).

        controls : liste de dict {lng, lat} ou tuples (lng, lat).
        Retourne {total_choice_score, avg_choice_score, leg_details}.

        choice_score par jambe = diversity_score × similarity_bonus
        similarity_bonus = 1.0 si (min_dist/max_dist) > 0.85, sinon ratio/0.85
        → 1.0 = deux routes distinctes ET longueurs quasi-égales (choix non-évident)
        """
        def _lnglat(c):
            if isinstance(c, dict):
                return c["lng"], c["lat"]
            return float(c[0]), float(c[1])

        import time as _t
        leg_details = []
        for i in range(len(controls) - 1):
            if t_deadline is not None and _t.time() > t_deadline:
                break  # budget épuisé — on arrête les jambes restantes
            lng_a, lat_a = _lnglat(controls[i])
            lng_b, lat_b = _lnglat(controls[i + 1])
            try:
                routes = self.get_k_routes(lng_a, lat_a, lng_b, lat_b, k=k)
                def _waypoints(r):
                    return [[round(lng, 6), round(lat, 6)] for lng, lat in r]

                if not routes:
                    leg_details.append({
                        "leg_idx": i, "n_routes": 0, "distances_m": [],
                        "choice_score": 0.0, "similarity_ratio": 0.0, "waypoints_list": [],
                    })
                    continue
                if len(routes) < 2:
                    leg_details.append({
                        "leg_idx": i, "n_routes": 1,
                        "distances_m": [round(self.route_length_m(routes[0]), 1)],
                        "choice_score": 0.0, "similarity_ratio": 0.0,
                        "waypoints_list": [_waypoints(routes[0])],
                    })
                    continue
                distances = [self.route_length_m(r) for r in routes]
                min_d, max_d = min(distances), max(distances)
                similarity_ratio = (min_d / max_d) if max_d > 0 else 1.0
                similarity_bonus = 1.0 if similarity_ratio > 0.85 else (similarity_ratio / 0.85)
                diversity = self._jaccard_from_routes(routes)  # pré-calculé, zéro appel nx supplémentaire
                choice_score = diversity * similarity_bonus
                leg_details.append({
                    "leg_idx": i,
                    "n_routes": len(routes),
                    "distances_m": [round(d, 1) for d in distances],
                    "choice_score": round(choice_score, 4),
                    "similarity_ratio": round(similarity_ratio, 4),
                    "waypoints_list": [_waypoints(r) for r in routes],
                })
            except Exception:
                leg_details.append({
                    "leg_idx": i, "n_routes": 0, "distances_m": [],
                    "choice_score": 0.0, "similarity_ratio": 0.0, "waypoints_list": [],
                })

        total = sum(d["choice_score"] for d in leg_details)
        avg = total / len(leg_details) if leg_details else 0.0
        return {
            "total_choice_score": round(total, 4),
            "avg_choice_score": round(avg, 4),
            "leg_details": leg_details,
        }

    # ── Infos graphe ───────────────────────────────────────────────────────────

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()
