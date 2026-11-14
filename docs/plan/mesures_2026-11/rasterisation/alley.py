import numpy as np
from shapely.geometry import Polygon
from shapely import affinity
from skimage.draw import polygon as sk_polygon
from scipy import ndimage as ndi
rng = np.random.default_rng(7)

def raster_poly(poly, res, n):
    xs, ys = np.asarray(poly.exterior.coords).T
    rr, cc = sk_polygon(ys / res - 0.5, xs / res - 0.5, shape=(n, n))
    m = np.zeros((n, n), bool); m[rr, cc] = True
    return m

def alley_open(res, w, trials=300, L=40.0):
    """Deux bâtiments rectangulaires séparés par une ruelle de largeur w (m), angle aléatoire.
    La ruelle relie-t-elle ses deux extrémités en 8-connexité (et en 4-connexité) ?"""
    n = int(120 / res); size = n * res
    ok8 = ok4 = 0
    for _ in range(trials):
        ang = rng.uniform(0, 180)
        cx, cy = size / 2 + rng.uniform(-res, res), size / 2 + rng.uniform(-res, res)
        # bâtiments : 2 rectangles L x 20 de part et d'autre de l'axe x, séparés de w
        b1 = Polygon([(-L/2, w/2), (L/2, w/2), (L/2, w/2 + 20), (-L/2, w/2 + 20)])
        b2 = Polygon([(-L/2, -w/2 - 20), (L/2, -w/2 - 20), (L/2, -w/2), (-L/2, -w/2)])
        # murs de fermeture latéraux pour forcer le passage par la ruelle
        blocks = []
        for b in (b1, b2):
            b = affinity.translate(affinity.rotate(b, ang, origin=(0, 0)), cx, cy)
            blocks.append(b)
        wall = np.zeros((n, n), bool)
        for b in blocks: wall |= raster_poly(b, res, n)
        free = ~wall
        # ne garder que les cellules libres DANS la ruelle (bande entre les 2 bâtiments) + 2 "places" aux extrémités
        a = np.radians(ang); d = np.array([np.cos(a), np.sin(a)]); nrm = np.array([-d[1], d[0]])
        rr, cc = np.nonzero(free); x = (cc + .5) * res - cx; y = (rr + .5) * res - cy
        u = x * d[0] + y * d[1]; v = x * nrm[0] + y * nrm[1]
        in_alley = (np.abs(u) <= L/2) & (np.abs(v) <= w/2 + 20)      # zone bâtie : seules les cellules de ruelle y sont libres
        end_a = (u < -L/2) & (u > -L/2 - 6) & (np.abs(v) < 6); end_b = (u > L/2) & (u < L/2 + 6) & (np.abs(v) < 6)
        keep = np.zeros((n, n), bool); sel = in_alley | end_a | end_b; keep[rr[sel], cc[sel]] = True
        for conn, name in ((np.ones((3, 3)), 8), (None, 4)):
            lab, k = ndi.label(keep, structure=conn)
            la = set(lab[rr[end_a], cc[end_a]]) - {0}; lb = set(lab[rr[end_b], cc[end_b]]) - {0}
            if la & lb:
                if name == 8: ok8 += 1
                else: ok4 += 1
    return ok8, ok4

for res in (0.5, 1.0, 2.0):
    for w in (1.0, 1.2, 1.6, 2.0, 3.0):
        o8, o4 = alley_open(res, w)
        print(f"res={res} m  ruelle {w} m : ouverte 8-conn {o8}/300 ; 4-conn {o4}/300")
