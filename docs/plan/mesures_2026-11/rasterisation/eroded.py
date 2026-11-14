"""Rastérisation prudente : une cellule est LIBRE ssi son centre est dans l'espace libre érodé de res*sqrt(2)/2.
Vérifie (1) pas de fuite au contact coin-à-coin, (2) ruelles étroites conservées."""
import numpy as np, time
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from shapely import affinity
from skimage.draw import polygon as sk_polygon
from scipy import ndimage as ndi
rng = np.random.default_rng(3)
S8 = np.ones((3, 3))

def fill_ring(coords, res, shape):
    xs, ys = np.asarray(coords)[:, 0], np.asarray(coords)[:, 1]
    return sk_polygon(ys / res - 0.5, xs / res - 0.5, shape=shape)

def raster_free(free, res, n):
    """free : (Multi)Polygon de l'espace libre déjà érodé. Retourne masque bool (True = libre)."""
    m = np.zeros((n, n), bool)
    polys = getattr(free, "geoms", [free])
    for p in polys:
        if p.is_empty: continue
        one = np.zeros((n, n), bool)
        rr, cc = fill_ring(p.exterior.coords, res, (n, n)); one[rr, cc] = True
        for hole in p.interiors:
            rr, cc = fill_ring(hole.coords, res, (n, n)); one[rr, cc] = False
        m |= one
    return m

def build(obstacles, size, res, eps=0.05):
    obst = unary_union([o.buffer(eps, join_style="mitre") for o in obstacles])
    free = box(0, 0, size, size).difference(obst)
    eroded = free.buffer(-res * 0.7072, join_style="mitre")
    return free, eroded

def corner_case(res, trials=200):
    n = int(80 / res); size = n * res; closed_vec = closed_ras = 0
    for _ in range(trials):
        ang = rng.uniform(0, 90); cx, cy = size/2 + rng.uniform(-res, res), size/2 + rng.uniform(-res, res)
        b1 = Polygon([(0, 0), (25, 0), (25, 25), (0, 25)]); b2 = Polygon([(-25, -25), (0, -25), (0, 0), (-25, 0)])
        obs = [affinity.translate(affinity.rotate(b, ang, origin=(0, 0)), cx, cy) for b in (b1, b2)]
        # murs fermant le pourtour : on ne teste que le voisinage du coin (disque 12 m)
        free, eroded = build(obs, size, res)
        m = raster_free(eroded, res, n)
        rr, cc = np.indices((n, n)); x = (cc + .5) * res - cx; y = (rr + .5) * res - cy
        disk = np.hypot(x, y) < 12
        lab, k = ndi.label(m & disk, structure=S8)
        a = np.radians(ang); d1 = np.array([np.cos(a), np.sin(a)]); d2 = np.array([-np.sin(a), np.cos(a)])
        u = x * d1[0] + y * d1[1]; v = x * d2[0] + y * d2[1]
        qa = disk & m & (u < -2) & (v > 2); qb = disk & m & (u > 2) & (v < -2)
        closed_ras += int(not ((set(np.unique(lab[qa])) - {0}) & (set(np.unique(lab[qb])) - {0})))
    return closed_ras

def alley_case(res, w, trials=200, L=40.0):
    n = int(120 / res); size = n * res; ok = 0
    for _ in range(trials):
        ang = rng.uniform(0, 180); cx, cy = size/2 + rng.uniform(-res, res), size/2 + rng.uniform(-res, res)
        b1 = Polygon([(-L/2, w/2), (L/2, w/2), (L/2, w/2 + 20), (-L/2, w/2 + 20)])
        b2 = Polygon([(-L/2, -w/2 - 20), (L/2, -w/2 - 20), (L/2, -w/2), (-L/2, -w/2)])
        obs = [affinity.translate(affinity.rotate(b, ang, origin=(0, 0)), cx, cy) for b in (b1, b2)]
        free, eroded = build(obs, size, res)
        m = raster_free(eroded, res, n)
        a = np.radians(ang); d = np.array([np.cos(a), np.sin(a)]); nrm = np.array([-d[1], d[0]])
        rr, cc = np.nonzero(m); x = (cc + .5) * res - cx; y = (rr + .5) * res - cy
        u = x * d[0] + y * d[1]; v = x * nrm[0] + y * nrm[1]
        in_alley = (np.abs(u) <= L/2) & (np.abs(v) <= w/2 + 20)
        end_a = (u < -L/2) & (u > -L/2 - 6) & (np.abs(v) < 6); end_b = (u > L/2) & (u < L/2 + 6) & (np.abs(v) < 6)
        keep = np.zeros((n, n), bool); sel = in_alley | end_a | end_b; keep[rr[sel], cc[sel]] = True
        lab, k = ndi.label(keep, structure=S8)
        ok += int(bool((set(lab[rr[end_a], cc[end_a]]) - {0}) & (set(lab[rr[end_b], cc[end_b]]) - {0})))
    return ok

for res in (0.25, 0.5, 1.0):
    t0 = time.perf_counter()
    print(f"res={res} m  coin-à-coin FERMÉ : {corner_case(res)}/200", end=" ; ")
    print(" ".join(f"ruelle {w} m ouverte {alley_case(res, w)}/200 ;" for w in (0.8, 1.0, 1.2, 1.6, 2.0, 2.5)), f"({time.perf_counter()-t0:.0f}s)")
