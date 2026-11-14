import numpy as np
from shapely.geometry import Polygon
from shapely import affinity
from skimage.draw import polygon as sk_polygon
from scipy import ndimage as ndi
rng = np.random.default_rng(11)
S8 = np.ones((3, 3))

def raster_poly(poly, res, n):
    xs, ys = np.asarray(poly.exterior.coords).T
    rr, cc = sk_polygon(ys / res - 0.5, xs / res - 0.5, shape=(n, n))
    m = np.zeros((n, n), bool); m[rr, cc] = True
    return m

def seal_diagonal_pinches(wall):
    """Ferme les passages diagonaux d'une seule cellule : motif 2x2 [mur, libre / libre, mur]."""
    w = wall.copy()
    a = w[:-1, :-1]; b = w[:-1, 1:]; c = w[1:, :-1]; d = w[1:, 1:]
    p1 = a & d & ~b & ~c          # murs sur la diagonale principale -> boucher b
    p2 = b & c & ~a & ~d          # murs sur l'anti-diagonale -> boucher a
    w[:-1, 1:] |= p1
    w[:-1, :-1] |= p2
    return w

def corner_touch_closed(res, trials=300, seal=True):
    """Deux bâtiments carrés qui se touchent par un coin : le passage doit être FERMÉ."""
    n = int(80 / res); size = n * res; closed = 0
    for _ in range(trials):
        ang = rng.uniform(0, 90); cx, cy = size/2 + rng.uniform(-res, res), size/2 + rng.uniform(-res, res)
        b1 = Polygon([(0, 0), (25, 0), (25, 25), (0, 25)]); b2 = Polygon([(-25, -25), (0, -25), (0, 0), (-25, 0)])
        wall = np.zeros((n, n), bool)
        for b in (b1, b2):
            wall |= raster_poly(affinity.translate(affinity.rotate(b, ang, origin=(0, 0)), cx, cy), res, n)
        if seal: wall = seal_diagonal_pinches(wall)
        # zone d'étude : disque de rayon 12 m autour du coin ; les 2 quadrants libres sont-ils reliés DANS ce disque ?
        rr, cc = np.indices((n, n)); x = (cc + .5) * res - cx; y = (rr + .5) * res - cy
        disk = np.hypot(x, y) < 12
        lab, k = ndi.label(~wall & disk, structure=S8)
        a = np.radians(ang); d1 = np.array([np.cos(a), np.sin(a)]); d2 = np.array([-np.sin(a), np.cos(a)])
        u = x * d1[0] + y * d1[1]; v = x * d2[0] + y * d2[1]
        qa = disk & ~wall & (u < -2) & (v > 2); qb = disk & ~wall & (u > 2) & (v < -2)
        la = set(np.unique(lab[qa])) - {0}; lb = set(np.unique(lab[qb])) - {0}
        closed += int(not (la & lb))
    return closed

def alley_open(res, w, trials=300, L=40.0, seal=True):
    n = int(120 / res); size = n * res; ok = 0
    for _ in range(trials):
        ang = rng.uniform(0, 180); cx, cy = size/2 + rng.uniform(-res, res), size/2 + rng.uniform(-res, res)
        b1 = Polygon([(-L/2, w/2), (L/2, w/2), (L/2, w/2 + 20), (-L/2, w/2 + 20)])
        b2 = Polygon([(-L/2, -w/2 - 20), (L/2, -w/2 - 20), (L/2, -w/2), (-L/2, -w/2)])
        wall = np.zeros((n, n), bool)
        for b in (b1, b2):
            wall |= raster_poly(affinity.translate(affinity.rotate(b, ang, origin=(0, 0)), cx, cy), res, n)
        if seal: wall = seal_diagonal_pinches(wall)
        a = np.radians(ang); d = np.array([np.cos(a), np.sin(a)]); nrm = np.array([-d[1], d[0]])
        rr, cc = np.nonzero(~wall); x = (cc + .5) * res - cx; y = (rr + .5) * res - cy
        u = x * d[0] + y * d[1]; v = x * nrm[0] + y * nrm[1]
        in_alley = (np.abs(u) <= L/2) & (np.abs(v) <= w/2 + 20)
        end_a = (u < -L/2) & (u > -L/2 - 6) & (np.abs(v) < 6); end_b = (u > L/2) & (u < L/2 + 6) & (np.abs(v) < 6)
        keep = np.zeros((n, n), bool); sel = in_alley | end_a | end_b; keep[rr[sel], cc[sel]] = True
        lab, k = ndi.label(keep, structure=S8)
        la = set(lab[rr[end_a], cc[end_a]]) - {0}; lb = set(lab[rr[end_b], cc[end_b]]) - {0}
        ok += int(bool(la & lb))
    return ok

for res in (0.5, 1.0):
    print(f"res={res} m  coin-à-coin fermé SANS scellement : {corner_touch_closed(res, seal=False)}/300 ; AVEC : {corner_touch_closed(res, seal=True)}/300")
    for w in (1.0, 1.2, 1.6, 2.0):
        print(f"   ruelle {w} m ouverte AVEC scellement (8-conn) : {alley_open(res, w, seal=True)}/300")
