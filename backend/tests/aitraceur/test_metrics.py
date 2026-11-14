"""Tests des indicateurs course_metrics() — 6 cas chiffrés du plan §0.6."""
import math
import pytest
from src.aitraceur.evalbench.metrics import course_metrics, CourseMetrics

BBOX_LARGE = (-1000.0, -1000.0, 1000.0, 1000.0)


class TestCarré:
    """Carré (0,0) (100,0) (100,100) (0,100) (0,0)."""

    def setup_method(self) -> None:
        self.pts = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
        self.m = course_metrics(self.pts, area_bbox=BBOX_LARGE, cluster_radius_m=60)

    def test_n_controls(self) -> None:
        assert self.m.n_controls == 3

    def test_length(self) -> None:
        assert self.m.length_m == pytest.approx(400.0)

    def test_leg_cv_zero(self) -> None:
        assert self.m.leg_cv == pytest.approx(0.0)

    def test_no_crossings(self) -> None:
        assert self.m.crossings == 0

    def test_no_doglegs(self) -> None:
        assert self.m.doglegs == 0

    def test_is_loop(self) -> None:
        assert self.m.is_loop is True

    def test_min_pair_dist(self) -> None:
        # paires : (0,0)-(100,0)=100, (0,0)-(100,100)=141.4, (0,0)-(0,100)=100,
        #          (100,0)-(100,100)=100, (100,0)-(0,100)=141.4, (100,100)-(0,100)=100
        # paire départ-arrivée exclue : mais départ == arrivée (boucle), donc (0,0) et (0,0)
        # → le minimum parmi les autres paires est 100
        assert self.m.min_pair_dist_m == pytest.approx(100.0)


class TestPapillon:
    """Papillon (0,0) (100,100) (100,0) (0,100) — un croisement."""

    def setup_method(self) -> None:
        self.pts = [(0, 0), (100, 100), (100, 0), (0, 100)]
        self.m = course_metrics(self.pts, area_bbox=BBOX_LARGE, cluster_radius_m=60)

    def test_crossings(self) -> None:
        assert self.m.crossings == 1

    def test_no_doglegs(self) -> None:
        assert self.m.doglegs == 0

    def test_not_loop(self) -> None:
        assert self.m.is_loop is False


class TestAllerRetour:
    """Aller-retour (0,0) (100,0) (10,5) (200,200) — dog-leg au 2ᵉ point."""

    def setup_method(self) -> None:
        self.pts = [(0, 0), (100, 0), (10, 5), (200, 200)]
        self.m = course_metrics(self.pts, area_bbox=BBOX_LARGE, cluster_radius_m=60)

    def test_doglegs(self) -> None:
        # Au point (100,0) : vecteur d'arrivée (100,0), vecteur de départ (-90,5)
        # cos(δ) = (100×(-90) + 0×5) / (100 × √(8125)) = -9000/9013.9 ≈ -0.9985
        # δ ≈ 176.8° >= 150° → dog-leg
        assert self.m.doglegs == 1


class TestAmas:
    """Amas avec R=60 : départ (-200,-200), postes (0,0)(30,0)(0,30)(500,500), arrivée (700,700)."""

    def setup_method(self) -> None:
        self.pts = [(-200, -200), (0, 0), (30, 0), (0, 30), (500, 500), (700, 700)]
        self.m = course_metrics(self.pts, area_bbox=(-500.0, -500.0, 1000.0, 1000.0), cluster_radius_m=60)

    def test_max_in_radius(self) -> None:
        # Postes : (0,0)(30,0)(0,30)(500,500)
        # Autour de (0,0) : dist(0,0)=0≤60, dist(30,0)=30≤60, dist(0,30)=30≤60 → 3 dans le disque
        # Autour de (30,0) : dist(0,0)=30≤60, dist(30,0)=0≤60, dist(0,30)=42.4≤60 → 3
        # Autour de (0,30) : dist(0,0)=30≤60, dist(30,0)=42.4≤60, dist(0,30)=0≤60 → 3
        # Autour de (500,500) : seul lui-même → 1
        assert self.m.max_in_radius == 3

    def test_n_clustered(self) -> None:
        # Postes ayant >= 2 autres postes à < 60m : (0,0), (30,0), (0,30) → 3
        assert self.m.n_clustered == 3

    def test_n_pairs_below_30m(self) -> None:
        # (0,0)-(30,0)=30 (strict < 30 → non), (0,0)-(0,30)=30 (non), (30,0)-(0,30)=42.4 (non)
        assert self.m.n_pairs_below_30m == 0

    def test_n_pairs_below_60m(self) -> None:
        # (0,0)-(30,0)=30<60✓, (0,0)-(0,30)=30<60✓, (30,0)-(0,30)=42.4<60✓ → 3
        assert self.m.n_pairs_below_60m == 3


class TestCouverture:
    """Couverture zone (0,0,400,400) ; points (50,50)(150,50)(350,350)."""

    def setup_method(self) -> None:
        # On met un départ fictif et une arrivée fictive pour avoir au moins 2 points
        # mais les 3 points du plan sont le départ, le seul poste, et l'arrivée
        self.pts = [(50, 50), (150, 50), (350, 350)]
        self.m = course_metrics(self.pts, area_bbox=(0.0, 0.0, 400.0, 400.0), cluster_radius_m=60)

    def test_coverage(self) -> None:
        # Zone 400×400, cases 100×100
        # (50,50)   → col=0, row=0 → case (0,0)
        # (150,50)  → col=1, row=0 → case (0,1)
        # (350,350) → col=3, row=3 → case (3,3)
        # 3 cases sur 16 = 0.1875
        assert self.m.coverage_4x4 == pytest.approx(3 / 16)


class TestInterdit:
    """Interdit : carré (40,40)-(60,60) ; points (50,50)(100,100)."""

    def setup_method(self) -> None:
        self.pts = [(50, 50), (100, 100)]
        forbidden_poly = [(40, 40), (60, 40), (60, 60), (40, 60)]
        self.m = course_metrics(
            self.pts, area_bbox=BBOX_LARGE,
            forbidden=[forbidden_poly], cluster_radius_m=60,
        )

    def test_forbidden_hits(self) -> None:
        assert self.m.forbidden_hits == 1
