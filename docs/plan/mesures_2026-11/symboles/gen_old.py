import json, re, collections, os
OOM = os.environ.get('OOM_DIR', 'mapper')   # clone de https://github.com/OpenOrienteering/mapper
T = json.load(open('symtables.json')); SEM = json.load(open('semantics.json'))
def main_of(code): return int(code.split('.')[0])
def kinds_of(k): return {'C': ['A', 'L']}.get(k, [k])
def load_crt(path):
    m = {}
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if not line or line.startswith('#'): continue
        new, old = line.split()[:2]
        m[old] = new
    return m
def sem_key(code, kind, table):
    full = f"{'.'.join(code.split('.')[:2])}/{kind}"; mainkey = f"{main_of(code)}/{kind}"
    return table.get(full) or table.get(mainkey)
def brief(s): return None if s is None else (s['fam'], s['pas'], s['v'], s['line'], s['site'])
def run(old_std, new_std, new_sem, crt_path):
    crt = load_crt(crt_path)
    new_kinds = {c: k for c, k, n, col in T[new_std]}
    by = collections.defaultdict(list)
    for code, kind, name, col in T[old_std]:
        m = main_of(code)
        if not (101 <= m <= 599): continue
        name = re.sub('<[^>]+>', '', name).strip()
        new = crt.get(code)
        for k in kinds_of(kind):
            if k == 'T': continue
            s = None
            if new is not None:
                s = sem_key(new, k, new_sem)
                if s is None:   # essayer l'autre type du symbole cible (ex. C→A)
                    for kk in kinds_of(new_kinds.get(new, k)):
                        s = s or sem_key(new, kk, new_sem)
            by[(m, k)].append((code, name, new, brief(s)))
    nomap, conflict, ok = [], [], 0
    for (m, k), items in sorted(by.items()):
        sems = {it[3] for it in items}
        if sems == {None}:
            nomap.append((m, k, [(c, n) for c, n, _, _ in items]))
        elif len(sems - {None}) > 1 or (None in sems and len(sems) > 1):
            conflict.append((m, k, items))
        else: ok += 1
    print(f"\n===== {old_std} → {new_std} : {len(by)} couples ; générés sans ambiguïté : {ok} ; sans correspondance : {len(nomap)} ; ambigus : {len(conflict)}")
    print("-- sans correspondance :")
    for m, k, it in nomap: print(f"   {m}/{k} : {it}")
    print("-- ambigus (sous-symboles de sens différents) :")
    for m, k, items in conflict:
        print(f"   {m}/{k} :")
        for c, n, new, s in items: print(f"        {c:10s} {n[:44]:44s} → {str(new):8s} {s}")
run('ISOM2000', 'ISOM2017-2', SEM['ISOM2017_2'], os.path.join(OOM, 'symbol sets', 'ISOM2000-ISOM 2017-2.crt'))
run('ISSOM2007', 'ISSprOM2019', SEM['ISSPROM2019'], os.path.join(OOM, 'symbol sets', 'ISSOM-ISSprOM 2019.crt'))
