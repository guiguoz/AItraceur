import time, inspect, numpy as np
from skimage.graph import MCP_Geometric
from scipy import ndimage as ndi
print("find_costs signature:", inspect.signature(MCP_Geometric.find_costs) if hasattr(inspect, 'signature') else '')
try:
    print(MCP_Geometric.find_costs.__doc__[:900])
except Exception as e:
    print('doc err', e)

rng = np.random.default_rng(0)

def city(n, block=60, street=8):
    """Grille de rues : cellules de bâtiment = inf, rues = 1.0 (résolution = 1 cellule)."""
    a = np.full((n, n), np.inf, dtype=np.float64)
    for k in range(0, n, block):
        a[k:k+street, :] = 1.0
        a[:, k:k+street] = 1.0
    return a

def forest(n):
    a = rng.choice([1.0, 1.25, 1.67, 2.5], size=(n//20+1, n//20+1), p=[0.5, 0.25, 0.15, 0.1])
    a = np.kron(a, np.ones((20, 20)))[:n, :n].astype(np.float64)
    return a

def run(name, costs, res_m, src, max_cost=None):
    t0 = time.perf_counter()
    m = MCP_Geometric(costs, fully_connected=True)
    kw = {}
    if max_cost is not None:
        kw['max_cumulative_cost'] = max_cost
    cum, tb = m.find_costs([src], **kw)
    dt = time.perf_counter() - t0
    reached = np.isfinite(cum).sum()
    print(f"{name}: grid={costs.shape} res={res_m}m  bound={max_cost}  reached={reached:,} cells  time={dt:.2f}s")
    return cum

# Sprint 1.5 km x 1.5 km at 0.5 m => 3000 x 3000
c = city(3000, block=120, street=16)   # pâtés de 60 m, rues de 8 m à 0,5 m/cellule
run("sprint 0.5m full", c, 0.5, (1500+4, 1500+4))
run("sprint 0.5m bounded 500 m (1000 cells)", c, 0.5, (1500+4, 1500+4), max_cost=1000)
c1 = city(1500, block=60, street=8)
run("sprint 1m full", c1, 1.0, (750+2, 750+2))
run("sprint 1m bounded 500 m", c1, 1.0, (750+2, 750+2), max_cost=500)
# Forest 3 km x 3 km at 5 m => 600 x 600 ; at 2 m => 1500 x 1500
f5 = forest(600); run("forest 5m full", f5, 5, (300, 300))
f2 = forest(1500); run("forest 2m full", f2, 2, (750, 750))
run("forest 2m bounded 1.5 km eq (750 cells x cost1)", f2, 2, (750, 750), max_cost=900)
# Connected components on 3000x3000
t0 = time.perf_counter(); lab, n = ndi.label(np.isfinite(c), structure=np.ones((3,3))); print(f"label 3000x3000: {n} comps in {time.perf_counter()-t0:.2f}s")
