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

    # ── Score de diversité d'itinéraire ───────────────────────────────────────

    def route_diversity_score(
        self,
        start_lng: float, start_lat: float,
        end_lng: float, end_lat: float,
        k: int = 3,
    ) -> float:
        """
        Score Jaccard de diversité entre les k meilleures routes [0.0, 1.0].
        0.0 = couloir unique (toutes routes identiques)
        1.0 = vraies alternatives distinctes
        """
        n_start = self._nearest_node(start_lng, start_lat)
        n_end = self._nearest_node(end_lng, end_lat)
        if n_start is None or n_end is None or n_start == n_end:
            return 0.0
        try:
            gen = nx.shortest_simple_paths(self.graph, n_start, n_end, weight="weight")
            paths = []
            for p in gen:
                paths.append(p)
                if len(paths) >= k:
                    break
        except (nx.NetworkXNoPath, nx.NodeNotFound, nx.NetworkXError):
            return 0.0

        if len(paths) < 2:
            return 0.0

        def path_edge_set(p):
            return frozenset(frozenset([p[i], p[i + 1]]) for i in range(len(p) - 1))

        edge_sets = [path_edge_set(p) for p in paths]
        diversities = []
        for i in range(len(edge_sets)):
            for j in range(i + 1, len(edge_sets)):
                union = len(edge_sets[i] | edge_sets[j])
                inter = len(edge_sets[i] & edge_sets[j])
                if union > 0:
                    diversities.append(1.0 - inter / union)

        return sum(diversities) / len(diversities) if diversities else 0.0

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
        Chaque route = liste de (lng, lat).
        """
        n_start = self._nearest_node(start_lng, start_lat)
        n_end = self._nearest_node(end_lng, end_lat)
        if n_start is None or n_end is None or n_start == n_end:
            return []
        try:
            gen = nx.shortest_simple_paths(self.graph, n_start, n_end, weight="weight")
            routes = []
            for path in gen:
                routes.append(path)
                if len(routes) >= k:
                    break
            return routes
        except (nx.NetworkXNoPath, nx.NodeNotFound, nx.NetworkXError):
            return []

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
