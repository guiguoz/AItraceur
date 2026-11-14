import re, sys, pathlib, unicodedata, difflib, os
TXT_DIR = os.environ.get('PDFTXT_DIR', 'pdftxt')   # textes extraits : pdftotext "<fichier>.pdf" "<fichier>.txt" (poppler)
DOCS = {
 'MF': TXT_DIR + '/Méthode Fédérale - Edition 2016.txt', 'GC': TXT_DIR + '/Guide de mise en place des circuits de couleur 2024.txt',
 'RTS': TXT_DIR + '/RTS_CO_(Ed.mai2025)_b6e41MU.txt', 'TP': TXT_DIR + '/TRACAGE PRINCIPES.txt', 'TAP': TXT_DIR + '/TRACAGE ASPECTS PRATIQUES.txt',
 'ISOM': TXT_DIR + '/ISOM2017_2_FR_EN  (mars2022).txt',
}
def norm(s):
    s = unicodedata.normalize('NFKC', s).lower()
    s = s.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"').replace('«', '"').replace('»', '"').replace('…', '...')
    s = re.sub(r'[­]', '', s); s = re.sub(r'-\s*\n\s*', '', s)      # césures
    s = re.sub(r'[^\w%]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()
TXT = {k: pathlib.Path(v).read_text(encoding='utf-8', errors='replace') for k, v in DOCS.items()}
PAGES = {k: [norm(p) for p in t.split('\f')] for k, t in TXT.items()}
def check(doc, frag):
    f = norm(frag)
    for i, pg in enumerate(PAGES[doc], 1):
        if f in pg: return f"OK   {doc} p.{i}"
    # approx : meilleure fenêtre
    best = (0, None, None)
    words = f.split()
    for i, pg in enumerate(PAGES[doc], 1):
        k = pg.find(' '.join(words[:3]))
        while k != -1:
            cand = pg[k:k + len(f) + 40]
            r = difflib.SequenceMatcher(None, f, cand[:len(f)]).ratio()
            if r > best[0]: best = (r, i, cand[:len(f) + 20])
            k = pg.find(' '.join(words[:3]), k + 1)
    return f"DIFF {doc} meilleur ratio {best[0]:.2f} p.{best[1]} :: trouvé « {best[2]} »"
for line in pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').splitlines():
    if not line.strip() or line.startswith('#'): continue
    doc, frag = line.split('|', 1)
    print(check(doc.strip(), frag), '<=', frag.strip()[:70])
