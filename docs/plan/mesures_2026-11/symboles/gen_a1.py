"""Construit les tables de sémantique de l'annexe A1 et vérifie qu'elles couvrent
tous les couples (numéro principal, type) des jeux de symboles de référence (codes 101-599)."""
import json, re, collections, sys
T = json.load(open('symtables.json'))

def main_of(code): return int(code.split('.')[0])
def kinds_of(k): return {'C': ['A', 'L']}.get(k, [k])

# (fam, pass, speed, line, site, obv, flags, note)
def S(fam, pas='libre', v=None, line=None, site=None, obv=None, flags='', note='', pen=None):
    return dict(fam=fam, pas=pas, v=v, line=line, site=site, obv=obv, flags=flags, note=note, pen=pen)

COMMON = {
 # ---------------- relief
 '101/L': S('relief', flags='courbe', note='courbe de niveau ; ligne de relief en phase 10'),
 '101/P': S('mise_en_page', note='tiret de pente : ignoré'),
 '102/L': S('relief', flags='courbe', note='courbe maîtresse'),
 '103/L': S('relief', flags='courbe', note='courbe de forme'),
 '103/P': S('mise_en_page', note='tiret de pente : ignoré'),
 '104/L': S('relief', 'lent', line='L2', site='extremite', obv=3, pen=3, note='talus'),
 '104/P': S('relief', site='ponctuel', obv=4, note='talus, taille minimale'),
 '105/L': S('relief', 'lent', line='L2', site='extremite', obv=3, pen=2, note='levée de terre'),
 '107/L': S('relief', 'lent', line='L3*', site='extremite', obv=3, pen=3, note='ravine'),
 '108/L': S('relief', line='L3*', site='extremite', obv=3, note='petite ravine'),
 '109/P': S('relief', site='ponctuel', obv=4, note='petite butte'),
 '110/P': S('relief', site='ponctuel', obv=4, note='butte allongée'),
 '111/P': S('relief', site='ponctuel', obv=4, note='petite dépression'),
 '112/P': S('relief', site='ponctuel', obv=4, note='trou'),
 '113/A': S('relief', v='V2', note='terrain accidenté : peu d\'effet sur la vitesse (ISOM 2017-2, 113)'),
 '113/P': S('mise_en_page', note='point de trame : ignoré'),
 '115/P': S('relief', site='ponctuel', obv=4, note='élément de relief particulier'),
 # ---------------- roche
 '201/L': S('roche', 'infranchissable', line='L3*', site='extremite', obv=3, flags='danger', note='falaise infranchissable'),
 '201/P': S('roche', 'infranchissable', site='ponctuel', obv=4, flags='danger', note='falaise infranchissable, taille minimale'),
 '202/L': S('roche', 'lent', line='L3*', site='extremite', obv=3, pen=10, note='falaise / paroi franchissable'),
 '202/P': S('roche', site='ponctuel', obv=4, note='falaise franchissable, taille minimale'),
 '203/P': S('roche', site='ponctuel', obv=4, note='trou rocheux, grotte'),
 '204/P': S('roche', site='ponctuel', obv=4, note='rocher'),
 '205/P': S('roche', site='ponctuel', obv=4, note='gros rocher'),
 '206/A': S('roche', 'infranchissable', site='petite_surface', obv=3, note='rocher gigantesque'),
 '207/P': S('roche', site='ponctuel', obv=4, note='groupe de rochers'),
 '208/A': S('roche', v='V2', note='champ de blocs'),
 '208/P': S('mise_en_page', note='triangle de trame : ignoré'),
 '210/A': S('roche', v='V3', note='sol pierreux, course ralentie (60-80 %)'),
 '210/P': S('mise_en_page', note='point de trame : ignoré'),
 '213/A': S('roche', v='V3', note='sol sablonneux (< 80 %)'),
 '214/A': S('roche', v='V2', note='dalle rocheuse'),
 # ---------------- eau
 '301/A': S('eau', 'infranchissable', line='L2', site='coin', obv=2, note='eau infranchissable ; la rive sert de ligne'),
 '301/L': S('eau', note='trait de rive : sans effet propre (la surface porte l\'obstacle)'),
 '302/A': S('eau', v='V4', line='L2', site='petite_surface', obv=2, note='eau peu profonde, franchissable (surface : la vitesse porte le ralentissement)'),
 '302/L': S('eau', note='trait de rive : sans effet propre'),
 '303/P': S('eau', site='ponctuel', obv=4, note='trou d\'eau'),
 '305/L': S('eau', 'lent', line='L2', site='jonction', obv=3, pen=2, note='petit cours d\'eau franchissable'),
 '306/L': S('eau', line='L3', site='jonction', obv=3, note='rigole, cours d\'eau saisonnier'),
 '307/A': S('eau', 'infranchissable', line='L3*', note='marais infranchissable'),
 '307/L': S('eau', note='contour de marais : sans effet propre'),
 '308/A': S('eau', v='V3', line='L3*', site='petite_surface', obv=3, note='marais'),
 '308/P': S('eau', site='ponctuel', obv=4, note='marais, taille minimale'),
 '309/L': S('eau', line='L3*', site='extremite', obv=3, note='marais étroit'),
 '310/A': S('eau', v='V2', note='marais peu visible'),
 '310/P': S('eau', site='ponctuel', obv=4, note='marais peu visible, taille minimale'),
 '311/P': S('eau', site='ponctuel', obv=4, note='puits, fontaine'),
 '312/P': S('eau', site='ponctuel', obv=4, note='source'),
 '313/P': S('eau', site='ponctuel', obv=4, note='élément d\'eau particulier'),
 # ---------------- végétation
 '401/A': S('vegetation', v='V1', line='L2', site='coin', obv=2, note='terrain découvert ; lisière = ligne nette', flags='ouvert'),
 '402/A': S('vegetation', v='V1', line='L3', note='terrain découvert, arbres dispersés'),
 '403/A': S('vegetation', v='V2', line='L3', site='coin', obv=3, note='terrain découvert encombré', flags='ouvert'),
 '404/A': S('vegetation', v='V2', note='découvert encombré, arbres dispersés'),
 '405/A': S('vegetation', v='V2', note='forêt (souvent : absence d\'objet)'),
 '406/A': S('vegetation', v='V3', note='course ralentie'),
 '407/A': S('vegetation', v='V3', note='course ralentie, bonne visibilité'),
 '408/A': S('vegetation', v='V4', note='marche'),
 '409/A': S('vegetation', v='V4', note='marche, bonne visibilité'),
 '412/A': S('vegetation', v='V2', line='L3', site='coin', obv=3, flags='ouvert, saisonnier', note='culture : peut être interdite selon la saison → à confirmer par le traceur'),
 '412/L': S('vegetation', note='contour : sans effet propre'),
 '413/A': S('vegetation', v='V2', line='L3', note='verger'),
 '414/A': S('vegetation', v='V3', line='L3', flags='directionnel', note='vigne'),
 '415/L': S('vegetation', line='L3', site='coin', obv=3, note='limite de culture nette'),
 '416/L': S('vegetation', line='L3', site='coin', obv=3, note='limite de végétation nette'),
 '417/P': S('vegetation', site='ponctuel', obv=3, note='arbre remarquable'),
 '418/P': S('vegetation', site='ponctuel', obv=4, note='buisson ou petit arbre remarquable'),
 '419/P': S('vegetation', site='ponctuel', obv=4, note='élément de végétation particulier'),
 # ---------------- ouvrages communs
 '506/L': S('chemin', v='V1', line='L1', site='jonction', obv=2, note='sentier'),
 '507/L': S('chemin', v='V2', line='L2', site='jonction', obv=3, note='sentier peu visible'),
 '508/L': S('chemin', v='V2', line='L2', site='jonction', obv=3, note='layon'),
 '510/L': S('ouvrage', line='L1', note='ligne électrique, téléphérique : aérien, sans effet au sol'),
 '511/L': S('ouvrage', line='L1', note='ligne électrique majeure'),
 '515/L': S('ouvrage', 'infranchissable', line='L1', site='coin', obv=2, note='mur infranchissable'),
 '518/L': S('ouvrage', 'infranchissable', line='L1', site='coin', obv=2, note='clôture infranchissable'),
 '519/P': S('ouvrage', 'ouvre', site='ponctuel', obv=3, note='point de passage'),
 '520/A': S('interdit', 'interdit', note='zone interdite d\'accès (olive)'),
 '520/L': S('interdit', note='trait de limite : sans effet propre (la surface porte l\'interdit)'),
 '521/A': S('batiment', 'infranchissable', site='coin', obv=1, note='bâtiment', line='L1'),
 '521/L': S('batiment', note='contour de bâtiment : sans effet propre'),
 '521/P': S('batiment', 'infranchissable', site='ponctuel', obv=2, note='bâtiment, taille minimale'),
 '522/A': S('batiment', v='V1', site='coin', obv=2, note='auvent, passage couvert : franchissable'),
 '522/L': S('batiment', note='contour d\'auvent : sans effet propre'),
 '524/P': S('ouvrage', site='ponctuel', obv=3, note='grande tour'),
 '525/P': S('ouvrage', site='ponctuel', obv=3, note='petite tour, affût'),
 '526/P': S('ouvrage', site='ponctuel', obv=4, note='cairn, borne, petit monument'),
 '527/P': S('ouvrage', site='ponctuel', obv=3, note='mangeoire'),
 '528/L': S('ouvrage', 'lent', line='L2*', site='coin', obv=3, pen=2, note='élément linéaire particulier'),
 '529/L': S('ouvrage', 'infranchissable', line='L2*', site='coin', obv=3, note='élément linéaire infranchissable'),
 '530/P': S('ouvrage', site='ponctuel', obv=3, note='élément particulier (cercle)'),
 '531/P': S('ouvrage', site='ponctuel', obv=3, note='élément particulier (croix)'),
}
ISOM = dict(COMMON); ISOM.update({
 '102/T': None,
 '106/L': S('relief', line='L3*', site='extremite', obv=3, note='levée de terre ruinée'),
 '114/A': S('relief', v='V3', note='terrain très accidenté : limite la vitesse'),
 '201/A': S('roche', 'infranchissable', note='falaise, représentation en plan'),
 '209/A': S('roche', v='V3', note='champ de blocs dense'),
 '211/A': S('roche', v='V4', note='sol pierreux, marche (20-60 %)'),
 '212/A': S('roche', v='V5', note='sol pierreux, progression difficile (< 20 %)'),
 '215/L': S('roche', 'lent', line='L2', site='extremite', obv=3, pen=3, note='tranchée'),
 '304/L': S('eau', 'lent', line='L1', site='jonction', obv=2, pen=6, note='cours d\'eau franchissable'),
 '410/A': S('vegetation', v='V5', note='progression difficile : FRANCHISSABLE en ISOM 2017-2'),
 '410/L': S('vegetation', 'lent', line='L2', pen=15, note='bande de végétation dense, largeur minimale'),
 '411/A': S('vegetation', 'infranchissable', note='végétation infranchissable (ISOM 2017, 1re édition)'),
 '501/A': S('chemin', v='V1', line='L1', site='coin', obv=2, note='zone pavée', flags='ouvert'),
 '501/L': S('chemin', note='bord de zone pavée ; chemin pavé si trait ≥ 0,30 mm (voir §2.5)'),
 '502/L': S('chemin', v='V1', line='L1', site='jonction', obv=2, note='route large'),
 '503/L': S('chemin', v='V1', line='L1', site='jonction', obv=2, note='route'),
 '504/L': S('chemin', v='V1', line='L1', site='jonction', obv=2, note='chemin carrossable'),
 '505/L': S('chemin', v='V1', line='L1', site='jonction', obv=2, note='chemin'),
 '509/L': S('ouvrage', line='L1', flags='voie_ferree', note='voie ferrée : traversée à confirmer par le traceur'),
 '512/L': S('ouvrage', 'ouvre', site='extremite', obv=2, note='pont, tunnel'),
 '512/P': S('ouvrage', 'ouvre', site='ponctuel', obv=2, note='pont, passerelle'),
 '513/L': S('ouvrage', 'lent', line='L1', site='coin', obv=2, pen=5, note='mur'),
 '514/L': S('ouvrage', line='L3', site='coin', obv=3, pen=1, note='mur ruiné'),
 '516/L': S('ouvrage', 'lent', line='L1', site='coin', obv=2, pen=5, note='clôture'),
 '517/L': S('ouvrage', line='L3*', site='coin', obv=3, pen=1, note='clôture ruinée'),
 '523/L': S('batiment', site='coin', obv=3, note='ruine'),
 '523/P': S('batiment', site='ponctuel', obv=3, note='ruine, taille minimale'),
 '532/L': S('chemin', v='V3', line='L1', site='extremite', obv=2, note='escalier'),
 '502/A': S('chemin', v='V1', flags='circulation', note='route à deux chaussées (emprise)'),
 '508/A': S('chemin', v='V2', note='layon (emprise, symbole combiné)'),
 '509/A': S('ouvrage', flags='voie_ferree', note='emprise de voie ferrée : à confirmer'),
 '511/A': S('ouvrage', note='ligne électrique majeure (symbole combiné) : sans effet au sol'),
})
SPR = dict(COMMON); SPR.update({
 '102/P': S('mise_en_page', note='tiret de pente : ignoré'),
 '102/T': None,
 '206/A': S('roche', 'infranchissable', site='petite_surface', obv=3, note='rocher gigantesque, pilier rocheux'),
 '410/A': S('vegetation', 'infranchissable', note='végétation INFRANCHISSABLE en ISSprOM 2019'),
 '410/L': S('vegetation', 'infranchissable', line='L2', site='coin', obv=3, note='haie infranchissable'),
 '406/L': S('vegetation', 'lent', line='L3', pen=4, note='bande de végétation lente, largeur minimale'),
 '408/L': S('vegetation', 'lent', line='L3', pen=10, note='bande de végétation dense, largeur minimale'),
 '501/A': S('chemin', v='V1', line='L1', site='coin', obv=2, flags='ouvert', note='zone pavée'),
 '501/L': S('chemin', note='marche ou bord de zone pavée ; chemin pavé si trait ≥ 0,30 mm (voir §2.5)'),
 '505/L': S('chemin', v='V1', line='L1', site='jonction', obv=2, note='sentier ou chemin non pavé'),
 '509/A': S('ouvrage', flags='voie_ferree', note='emprise de voie ferrée : à confirmer'),
 '509/L': S('ouvrage', line='L1', flags='voie_ferree', note='voie ferrée, tramway : traversée à confirmer'),
 '512/L': S('ouvrage', 'ouvre', site='extremite', obv=2, flags='multi_niveaux', note='pont, passage souterrain, tunnel'),
 '513/L': S('ouvrage', 'lent', line='L1', site='coin', obv=2, pen=4, note='mur franchissable, mur de soutènement franchissable'),
 '516/L': S('ouvrage', 'lent', line='L1', site='coin', obv=2, pen=4, note='clôture ou barrière franchissable'),
 '522/P': S('batiment', 'infranchissable', note='pilier : obstacle, pas un site'),
 '532/L': S('chemin', v='V3', line='L1', site='extremite', obv=2, note='escalier'),
})
for k in ('104/P', '106/L', '114/A', '201/A', '209/A', '211/A', '212/A', '215/L', '304/L', '411/A', '502/L', '503/L', '504/L', '512/P', '514/L', '517/L', '523/L', '523/P'):
    SPR.pop(k, None)

def check(std, table, name):
    ref = collections.defaultdict(set); names = {}
    for code, kind, nm, col in T[std]:
        m = main_of(code)
        if not (101 <= m <= 599): continue
        for k in kinds_of(kind):
            ref[(m, k)].add(code)
            names.setdefault((m, k), re.sub('<[^>]+>', '', nm).strip())
    missing = sorted(k for k in ref if k[1] != 'T' and f"{k[0]}/{k[1]}" not in table)
    extra = sorted(k for k in table if table[k] is not None and (int(k.split('/')[0]), k.split('/')[1]) not in ref)
    print(f"[{name}] couples (numéro principal, type) de référence : {len([k for k in ref if k[1] != 'T'])} ; manquants : {missing} ; en trop : {extra}", file=sys.stderr)
    return ref, names

def emit(std, table, title):
    ref, names = check(std, table, title)
    out = [f"| Clé | Nom de référence | Famille | Passabilité | Vitesse | Ligne | Site | Évid. | Drapeaux | Remarque |",
           "|-----|------------------|---------|-------------|---------|-------|------|-------|----------|----------|"]
    for key in sorted((k for k in table if table[k] is not None), key=lambda s: (int(s.split('/')[0]), s.split('/')[1])):
        s = table[key]; m, k = int(key.split('/')[0]), key.split('/')[1]
        nm = names.get((m, k), '—')
        pas = s['pas'] + (f" ({s['pen']} s)" if s['pen'] else '')
        out.append(f"| `{key}` | {nm} | {s['fam']} | {pas} | {s['v'] or '—'} | {s['line'] or '—'} | {s['site'] or '—'} | {s['obv'] or '—'} | {s['flags'] or '—'} | {s['note']} |")
    return "\n".join(out)

open('isom2017_2.md', 'w').write(emit('ISOM2017-2', ISOM, 'ISOM 2017-2'))
open('issprom2019.md', 'w').write(emit('ISSprOM2019', SPR, 'ISSprOM 2019'))
json.dump({'ISOM2017_2': {k: v for k, v in ISOM.items() if v}, 'ISSPROM2019': {k: v for k, v in SPR.items() if v}}, open('semantics.json', 'w'), ensure_ascii=False, indent=1)
print(len([v for v in ISOM.values() if v]), len([v for v in SPR.values() if v]))
