import time, warnings, numpy as np
from skimage.graph import MCP_Geometric, MCP
from scipy import ndimage as ndi
print([l.strip() for l in MCP.__doc__.splitlines() if 'negative' in l.lower() or 'inf' in l.lower() or 'impass' in l.lower()])
rng = np.random.default_rng(0)
def city(n, block, street):
    a = np.full((n, n), np.inf, dtype=np.float64)
    for k in range(0, n, block):
        a[k:k+street, :] = 1.0
        a[:, k:k+street] = 1.0
    return a
def forest(n):
    a = rng.choice([1.0, 1.25, 1.67, 2.5], size=(n//20+1, n//20+1), p=[0.5, 0.25, 0.15, 0.1])
    return np.kron(a, np.ones((20, 20)))[:n, :n].astype(np.float64)
def run(name, costs, src, window=None):
    t0 = time.perf_counter()
    if window is not None:
        r, c = src
        r0, r1 = max(0, r-window), min(costs.shape[0], r+window+1)
        c0, c1 = max(0, c-window), min(costs.shape[1], c+window+1)
        sub = costs[r0:r1, c0:c1]; s = (r-r0, c-c0)
    else:
        sub = costs; s = src
    m = MCP_Geometric(sub, fully_connected=True)
    cum, tb = m.find_costs([s])
    dt = time.perf_counter() - t0
    print(f"{name}: grid={sub.shape} reached={int(np.isfinite(cum).sum()):,} time={dt:.2f}s  max_cost={np.nanmax(cum[np.isfinite(cum)]):.0f}")
    return cum, m, (sub, s)

c = city(3000, 120, 16)
cum, m, _ = run("sprint 0.5m carte entière (1,5 km)", c, (1444, 1444))
run("sprint 0.5m fenêtre ±500 m", c, (1444, 1444), window=1000)
run("sprint 0.5m fenêtre ±300 m", c, (1444, 1444), window=600)
c1 = city(1500, 60, 8)
run("sprint 1m carte entière", c1, (722, 722))
run("sprint 1m fenêtre ±500 m", c1, (722, 722), window=500)
f5 = forest(600); run("forêt 5m carte entière (3 km)", f5, (300, 300))
f3 = forest(1000); run("forêt 3m carte entière (3 km)", f3, (500, 500))
f2 = forest(1500); cumf, mf, _ = run("forêt 2m carte entière (3 km)", f2, (750, 750))
# traceback timing
t0=time.perf_counter(); p = mf.traceback((100, 1400)); print("traceback len", len(p), f"{time.perf_counter()-t0:.3f}s")
# corridor: second field + combine
t0=time.perf_counter(); m2 = MCP_Geometric(f2, fully_connected=True); cumb,_ = m2.find_costs([(100,1400)]); tot = cumf + cumb; tab = cumf[100,1400]
corr = tot <= 1.05*tab; mid = corr & (np.abs(cumf-cumb) <= 0.02*tab); lab, n = ndi.label(mid, structure=np.ones((3,3)))
print(f"couloir 5 % : {int(corr.sum()):,} cellules ; porte médiane : {n} composante(s) ; {time.perf_counter()-t0:.2f}s (dont 2e champ)")
