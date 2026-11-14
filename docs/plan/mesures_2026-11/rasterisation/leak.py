import numpy as np, time
from shapely.geometry import LineString
from skimage.draw import polygon as sk_polygon
from scipy import ndimage as ndi
rng = np.random.default_rng(1)

def rasterize_barrier(line, res, n, half):
    """Marque les cellules dont le centre est à moins de `half` mètres de la ligne."""
    poly = line.buffer(half, cap_style="square", join_style="mitre")
    xs, ys = np.asarray(poly.exterior.coords).T
    # centre de la cellule (r, c) = ((c + 0.5) * res, (r + 0.5) * res)
    rr, cc = sk_polygon(ys / res - 0.5, xs / res - 0.5, shape=(n, n))
    m = np.zeros((n, n), bool); m[rr, cc] = True
    return m

def leaks(res, half_factor, trials=400, n=120):
    bad = 0
    size = n * res
    for _ in range(trials):
        # ligne traversant tout le carré, angle et décalage aléatoires, éventuellement brisée
        ang = rng.uniform(0, np.pi); off = rng.uniform(0.3, 0.7) * size
        d = np.array([np.cos(ang), np.sin(ang)]); p = np.array([size/2, size/2]) + (off - size/2) * np.array([-d[1], d[0]]) * 0.5
        a = p - d * size * 2; b = p + d * size * 2
        mid = p + rng.normal(0, size * 0.05, 2)
        line = LineString([a, mid, b])
        wall = rasterize_barrier(line, res, n, half_factor * res)
        free = ~wall
        lab, k = ndi.label(free, structure=np.ones((3, 3)))   # 8-connexité
        # deux côtés : signe par rapport à la ligne (approx. via segment a-b)
        rr, cc = np.nonzero(free)
        x = (cc + 0.5) * res; y = (rr + 0.5) * res
        # côté = signe de la distance signée à la polyligne (utilise le segment le plus proche)
        def side(px, py, s0, s1):
            return np.sign((s1[0]-s0[0])*(py-s0[1]) - (s1[1]-s0[1])*(px-s0[0]))
        d1 = np.hypot(x-mid[0], y-mid[1])
        t = ((x-a[0])*(mid[0]-a[0]) + (y-a[1])*(mid[1]-a[1])) / ((mid[0]-a[0])**2 + (mid[1]-a[1])**2)
        s = np.where(t <= 1.0, side(x, y, a, mid), side(x, y, mid, b))
        # garder les cellules clairement d'un côté (loin du coude)
        keep = d1 > 6 * res
        labs = lab[rr, cc]
        pos = set(np.unique(labs[keep & (s > 0)])); neg = set(np.unique(labs[keep & (s < 0)]))
        if pos & neg: bad += 1
    return bad

for hf in (0.5, 0.6, 0.71, 0.75, 1.0):
    t0 = time.perf_counter(); b = leaks(0.5, hf); print(f"demi-largeur = {hf:.2f} x res : {b} fuite(s) sur 400 ({time.perf_counter()-t0:.1f}s)")

# passages : deux murs colinéaires séparés par une ouverture g ; reste-t-elle ouverte ?
def gap_open(res, g, half_factor, n=160, trials=200):
    ok = 0; size = n * res
    for _ in range(trials):
        ang = rng.uniform(0, np.pi); d = np.array([np.cos(ang), np.sin(ang)])
        c = np.array([size/2, size/2]) + rng.uniform(-res, res, 2)
        l1 = LineString([c - d * size * 2, c - d * g / 2]); l2 = LineString([c + d * g / 2, c + d * size * 2])
        wall = np.zeros((n, n), bool)
        for l in (l1, l2):
            poly = l.buffer(half_factor * res, cap_style="flat", join_style="mitre")
            xs, ys = np.asarray(poly.exterior.coords).T
            rr, cc = sk_polygon(ys / res - 0.5, xs / res - 0.5, shape=(n, n)); wall[rr, cc] = True
        lab, k = ndi.label(~wall, structure=np.ones((3, 3)))
        nrm = np.array([-d[1], d[0]])
        pa = c + nrm * size * 0.3; pb = c - nrm * size * 0.3
        la = lab[int(pa[1] / res), int(pa[0] / res)]; lb = lab[int(pb[1] / res), int(pb[0] / res)]
        ok += int(la == lb and la != 0)
    return ok
for res in (0.5, 1.0):
    for g in (1.0, 1.5, 2.0, 2.5, 3.0):
        print(f"res={res} m, ouverture {g} m : ouverte dans {gap_open(res, g, 0.75)}/200 cas")
