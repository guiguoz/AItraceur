# Annexe A1 — Symboles : tables de référence et rôles

Cette annexe est la source des fichiers `backend/src/aitraceur/symbols/semantics/*.json` (phase 2,
étape 2.2). Elle remplace toutes les tables de symboles du dépôt (constat C4).

## 1. Principes de lecture

1. **Quatre normes**, quatre tables : ISOM 2017-2 et ISSprOM 2019 (actuelles), ISOM 2000 et
   ISSOM 2007 (anciennes, encore très présentes dans les cartes de club). Le même numéro n'a pas le
   même sens d'une norme à l'autre : aucune table « toutes normes » n'est permise.
2. **Clé = numéro principal + type d'objet** : `521/A` (bâtiment en surface), `521/L` (son contour),
   `521/P` (bâtiment de taille minimale). Types : `P` point, `L` ligne, `A` surface. Un symbole
   « combiné » des jeux de référence (surface + contour) compte pour `A` et pour `L`.
3. **Clé précise facultative** = deux premiers niveaux du code + type (`526.2/A`), utilisée
   seulement là où la norme officielle distingue deux sens sous le même numéro principal (§4).
   Elle l'emporte sur la clé générale.
4. Source des numéros, des noms et des types : jeux de symboles d'OpenOrienteering Mapper
   (`symbol sets/src/*.xmap`, GPL-3.0), 191 symboles pour ISOM 2017-2, 185 pour ISSprOM 2019, 157
   pour ISOM 2000, 169 pour ISSOM. Les tables ci-dessous ont été **générées et vérifiées par
   programme** contre ces jeux le 10 novembre 2026 : 121 couples (numéro principal, type) pour
   ISOM 2017-2, 104 pour ISSprOM 2019, aucun manquant, aucun en trop.
5. Source des rôles : texte de la norme ISOM 2017-2 (`docs/ISOM2017_2_FR_EN  (mars2022).pdf`),
   documents FFCO pour les lignes (§3.1) et l'évidence des postes (§3.2). Quand le rôle est un choix
   de ce plan et non une lecture de texte, la remarque le dit ou la classe porte un astérisque.

### Colonnes

| Colonne | Valeurs | Sens |
|---------|---------|------|
| Famille | `relief` `roche` `eau` `vegetation` `chemin` `ouvrage` `batiment` `interdit` `mise_en_page` | Regroupement pour l'affichage et les règles. |
| Passabilité | `libre` ; `lent (n s)` ; `infranchissable` ; `interdit` ; `ouvre` | `lent` ne concerne que les **lignes** : n secondes perdues à chaque franchissement (valeur initiale, `source="implementation"`, à caler en phase 9). Une surface qui ralentit le fait par sa classe de vitesse. `ouvre` rouvre un passage dans un infranchissable (pont, tunnel, point de passage). |
| Vitesse | `V1` … `V5` | Catégories de la norme ISOM 2017-2 §2.3 « Capacité à courir » (p. 9-10 du PDF) : V1 > 100 % (pelouse, zone pavée, chemin) ; V2 80–100 % (pré non entretenu, forêt ouverte) ; V3 60–80 % ; V4 20–60 % ; V5 < 20 %. |
| Ligne | `L1` `L2` `L3` | « Types de lignes » FFCO (§3.1). Pour une surface, c'est la classe de son **bord**. Astérisque : classement de ce plan, l'élément n'étant pas cité par la FFCO. |
| Site | `jonction` `coin` `extremite` `ponctuel` `petite_surface` | Façon dont l'objet fournit des emplacements de poste (phase 3). `jonction` : jonctions, croisements, coudes et extrémités d'un réseau de chemins ou de cours d'eau. `coin` : angles et extrémités. |
| Évid. | 1 à 4 | Évidence de base du site (§3.2). |
| Drapeaux | `ouvert` `saisonnier` `voie_ferree` `circulation` `multi_niveaux` `directionnel` `danger` `courbe` | Voir §3.3. |

## 2. Normes actuelles

### 2.1 — ISOM 2017-2 (cartes de forêt, 1:15 000 et 1:10 000)

| Clé | Nom de référence | Famille | Passabilité | Vitesse | Ligne | Site | Évid. | Drapeaux | Remarque |
|-----|------------------|---------|-------------|---------|-------|------|-------|----------|----------|
| `101/L` | Contour | relief | libre | — | — | — | — | courbe | courbe de niveau ; ligne de relief en phase 10 |
| `101/P` | Slope line, contour | mise_en_page | libre | — | — | — | — | — | tiret de pente : ignoré |
| `102/L` | Index contour | relief | libre | — | — | — | — | courbe | courbe maîtresse |
| `103/L` | Form line | relief | libre | — | — | — | — | courbe | courbe de forme |
| `103/P` | Slope line, formline | mise_en_page | libre | — | — | — | — | — | tiret de pente : ignoré |
| `104/L` | Earth bank | relief | lent (3 s) | — | L2 | extremite | 3 | — | talus |
| `104/P` | Earth bank, minimum size | relief | libre | — | — | ponctuel | 4 | — | talus, taille minimale |
| `105/L` | Earth wall | relief | lent (2 s) | — | L2 | extremite | 3 | — | levée de terre |
| `106/L` | Ruined earth wall | relief | libre | — | L3* | extremite | 3 | — | levée de terre ruinée |
| `107/L` | Erosion gully | relief | lent (3 s) | — | L3* | extremite | 3 | — | ravine |
| `108/L` | Small erosion gully | relief | libre | — | L3* | extremite | 3 | — | petite ravine |
| `109/P` | Small knoll | relief | libre | — | — | ponctuel | 4 | — | petite butte |
| `110/P` | Small elongated knoll | relief | libre | — | — | ponctuel | 4 | — | butte allongée |
| `111/P` | Small depression | relief | libre | — | — | ponctuel | 4 | — | petite dépression |
| `112/P` | Pit | relief | libre | — | — | ponctuel | 4 | — | trou |
| `113/A` | Broken ground | relief | libre | V2 | — | — | — | — | terrain accidenté : peu d'effet sur la vitesse (ISOM 2017-2, 113) |
| `113/P` | Broken ground, individual dot | mise_en_page | libre | — | — | — | — | — | point de trame : ignoré |
| `114/A` | Very broken ground | relief | libre | V3 | — | — | — | — | terrain très accidenté : limite la vitesse |
| `115/P` | Prominent landform feature | relief | libre | — | — | ponctuel | 4 | — | élément de relief particulier |
| `201/A` | Impassable cliff, plan shape representation (from ISOM2000) | roche | infranchissable | — | — | — | — | — | falaise, représentation en plan |
| `201/L` | Impassable cliff | roche | infranchissable | — | L3* | extremite | 3 | danger | falaise infranchissable |
| `201/P` | Impassable cliff, minimum size | roche | infranchissable | — | — | ponctuel | 4 | danger | falaise infranchissable, taille minimale |
| `202/L` | Cliff | roche | lent (10 s) | — | L3* | extremite | 3 | — | falaise / paroi franchissable |
| `202/P` | Cliff, minimum size | roche | libre | — | — | ponctuel | 4 | — | falaise franchissable, taille minimale |
| `203/P` | Rocky pit or cave (without a distinct entrance) | roche | libre | — | — | ponctuel | 4 | — | trou rocheux, grotte |
| `204/P` | Boulder | roche | libre | — | — | ponctuel | 4 | — | rocher |
| `205/P` | Large boulder | roche | libre | — | — | ponctuel | 4 | — | gros rocher |
| `206/A` | Gigantic boulder | roche | infranchissable | — | — | petite_surface | 3 | — | rocher gigantesque |
| `207/P` | Boulder cluster | roche | libre | — | — | ponctuel | 4 | — | groupe de rochers |
| `208/A` | Boulder field | roche | libre | V2 | — | — | — | — | champ de blocs |
| `208/P` | Boulder field, single triangle | mise_en_page | libre | — | — | — | — | — | triangle de trame : ignoré |
| `209/A` | Dense boulder field | roche | libre | V3 | — | — | — | — | champ de blocs dense |
| `210/A` | Stony ground, slow running | roche | libre | V3 | — | — | — | — | sol pierreux, course ralentie (60-80 %) |
| `210/P` | Stony ground, individual dot | mise_en_page | libre | — | — | — | — | — | point de trame : ignoré |
| `211/A` | Stony ground, walk | roche | libre | V4 | — | — | — | — | sol pierreux, marche (20-60 %) |
| `212/A` | Stony ground, fight | roche | libre | V5 | — | — | — | — | sol pierreux, progression difficile (< 20 %) |
| `213/A` | Sandy ground | roche | libre | V3 | — | — | — | — | sol sablonneux (< 80 %) |
| `214/A` | Bare rock | roche | libre | V2 | — | — | — | — | dalle rocheuse |
| `215/L` | Trench | roche | lent (3 s) | — | L2 | extremite | 3 | — | tranchée |
| `301/A` | Uncrossable body of water (full colour), with bank line | eau | infranchissable | — | L2 | coin | 2 | — | eau infranchissable ; la rive sert de ligne |
| `301/L` | Uncrossable body of water (full colour), with bank line | eau | libre | — | — | — | — | — | trait de rive : sans effet propre (la surface porte l'obstacle) |
| `302/A` | Shallow body of water, with solid outline | eau | libre | V4 | L2 | petite_surface | 2 | — | eau peu profonde, franchissable (surface : la vitesse porte le ralentissement) |
| `302/L` | Shallow body of water, with solid outline | eau | libre | — | — | — | — | — | trait de rive : sans effet propre |
| `303/P` | Waterhole | eau | libre | — | — | ponctuel | 4 | — | trou d'eau |
| `304/L` | Crossable watercourse | eau | lent (6 s) | — | L1 | jonction | 2 | — | cours d'eau franchissable |
| `305/L` | Small crossable watercourse | eau | lent (2 s) | — | L2 | jonction | 3 | — | petit cours d'eau franchissable |
| `306/L` | Minor/seasonal water channel | eau | libre | — | L3 | jonction | 3 | — | rigole, cours d'eau saisonnier |
| `307/A` | Uncrossable marsh, with outline | eau | infranchissable | — | L3* | — | — | — | marais infranchissable |
| `307/L` | Uncrossable marsh, with outline | eau | libre | — | — | — | — | — | contour de marais : sans effet propre |
| `308/A` | Marsh | eau | libre | V3 | L3* | petite_surface | 3 | — | marais |
| `308/P` | Marsh, minimum size | eau | libre | — | — | ponctuel | 4 | — | marais, taille minimale |
| `309/L` | Narrow marsh | eau | libre | — | L3* | extremite | 3 | — | marais étroit |
| `310/A` | Indistinct marsh | eau | libre | V2 | — | — | — | — | marais peu visible |
| `310/P` | Indistinct marsh, minimum size | eau | libre | — | — | ponctuel | 4 | — | marais peu visible, taille minimale |
| `311/P` | Well, fountain or water tank | eau | libre | — | — | ponctuel | 4 | — | puits, fontaine |
| `312/P` | Spring | eau | libre | — | — | ponctuel | 4 | — | source |
| `313/P` | Prominent water feature | eau | libre | — | — | ponctuel | 4 | — | élément d'eau particulier |
| `401/A` | Open land | vegetation | libre | V1 | L2 | coin | 2 | ouvert | terrain découvert ; lisière = ligne nette |
| `402/A` | Open land with scattered trees | vegetation | libre | V1 | L3 | — | — | — | terrain découvert, arbres dispersés |
| `403/A` | Rough open land | vegetation | libre | V2 | L3 | coin | 3 | ouvert | terrain découvert encombré |
| `404/A` | Rough open land with scattered trees | vegetation | libre | V2 | — | — | — | — | découvert encombré, arbres dispersés |
| `405/A` | Forest | vegetation | libre | V2 | — | — | — | — | forêt (souvent : absence d'objet) |
| `406/A` | Vegetation: slow running | vegetation | libre | V3 | — | — | — | — | course ralentie |
| `407/A` | Vegetation: slow running, good visibility | vegetation | libre | V3 | — | — | — | — | course ralentie, bonne visibilité |
| `408/A` | Vegetation: walk | vegetation | libre | V4 | — | — | — | — | marche |
| `409/A` | Vegetation: walk, good visibility | vegetation | libre | V4 | — | — | — | — | marche, bonne visibilité |
| `410/A` | Vegetation: fight | vegetation | libre | V5 | — | — | — | — | progression difficile : FRANCHISSABLE en ISOM 2017-2 |
| `410/L` | Vegetation: fight, minimum width | vegetation | lent (15 s) | — | L2 | — | — | — | bande de végétation dense, largeur minimale |
| `411/A` | Vegetation, impassable (from ISOM 2017, first edition) | vegetation | infranchissable | — | — | — | — | — | végétation infranchissable (ISOM 2017, 1re édition) |
| `412/A` | Cultivated land | vegetation | libre | V2 | L3 | coin | 3 | ouvert, saisonnier | culture : peut être interdite selon la saison → à confirmer par le traceur |
| `412/L` | Cultivated land | vegetation | libre | — | — | — | — | — | contour : sans effet propre |
| `413/A` | Orchard | vegetation | libre | V2 | L3 | — | — | — | verger |
| `414/A` | Vineyard or similar | vegetation | libre | V3 | L3 | — | — | directionnel | vigne |
| `415/L` | Distinct cultivation boundary | vegetation | libre | — | L3 | coin | 3 | — | limite de culture nette |
| `416/L` | Distinct vegetation boundary | vegetation | libre | — | L3 | coin | 3 | — | limite de végétation nette |
| `417/P` | Prominent large tree | vegetation | libre | — | — | ponctuel | 3 | — | arbre remarquable |
| `418/P` | Prominent bush or tree | vegetation | libre | — | — | ponctuel | 4 | — | buisson ou petit arbre remarquable |
| `419/P` | Prominent vegetation feature | vegetation | libre | — | — | ponctuel | 4 | — | élément de végétation particulier |
| `501/A` | Paved area, with bounding line | chemin | libre | V1 | L1 | coin | 2 | ouvert | zone pavée |
| `501/L` | Paved area, with bounding line | chemin | libre | — | — | — | — | — | bord de zone pavée ; chemin pavé si trait ≥ 0,30 mm (voir §2.5) |
| `502/A` | Road with two carriageways | chemin | libre | V1 | — | — | — | circulation | route à deux chaussées (emprise) |
| `502/L` | Wide road, minimum width | chemin | libre | V1 | L1 | jonction | 2 | — | route large |
| `503/L` | Road | chemin | libre | V1 | L1 | jonction | 2 | — | route |
| `504/L` | Vehicle track | chemin | libre | V1 | L1 | jonction | 2 | — | chemin carrossable |
| `505/L` | Footpath | chemin | libre | V1 | L1 | jonction | 2 | — | chemin |
| `506/L` | Small footpath | chemin | libre | V1 | L1 | jonction | 2 | — | sentier |
| `507/L` | Less distinct small footpath | chemin | libre | V2 | L2 | jonction | 3 | — | sentier peu visible |
| `508/A` | Narrow ride, easy running | chemin | libre | V2 | — | — | — | — | layon (emprise, symbole combiné) |
| `508/L` | Narrow ride | chemin | libre | V2 | L2 | jonction | 3 | — | layon |
| `509/A` | Railway | ouvrage | libre | — | — | — | — | voie_ferree | emprise de voie ferrée : à confirmer |
| `509/L` | Railway | ouvrage | libre | — | L1 | — | — | voie_ferree | voie ferrée : traversée à confirmer par le traceur |
| `510/L` | Power line, cableway or skilift | ouvrage | libre | — | L1 | — | — | — | ligne électrique, téléphérique : aérien, sans effet au sol |
| `511/A` | Major power line, large carrying masts | ouvrage | libre | — | — | — | — | — | ligne électrique majeure (symbole combiné) : sans effet au sol |
| `511/L` | Major power line, minimum width | ouvrage | libre | — | L1 | — | — | — | ligne électrique majeure |
| `512/L` | Bridge / tunnel | ouvrage | ouvre | — | — | extremite | 2 | — | pont, tunnel |
| `512/P` | Bridge / tunnel, minimum size | ouvrage | ouvre | — | — | ponctuel | 2 | — | pont, passerelle |
| `513/L` | Wall | ouvrage | lent (5 s) | — | L1 | coin | 2 | — | mur |
| `514/L` | Ruined wall | ouvrage | libre (1 s) | — | L3 | coin | 3 | — | mur ruiné |
| `515/L` | Impassable wall | ouvrage | infranchissable | — | L1 | coin | 2 | — | mur infranchissable |
| `516/L` | Fence | ouvrage | lent (5 s) | — | L1 | coin | 2 | — | clôture |
| `517/L` | Ruined fence | ouvrage | libre (1 s) | — | L3* | coin | 3 | — | clôture ruinée |
| `518/L` | Impassable fence | ouvrage | infranchissable | — | L1 | coin | 2 | — | clôture infranchissable |
| `519/P` | Crossing point | ouvrage | ouvre | — | — | ponctuel | 3 | — | point de passage |
| `520/A` | Area that shall not be entered | interdit | interdit | — | — | — | — | — | zone interdite d'accès (olive) |
| `520/L` | Area that shall not be entered, solid colour, bounding line | interdit | libre | — | — | — | — | — | trait de limite : sans effet propre (la surface porte l'interdit) |
| `521/A` | Building | batiment | infranchissable | — | L1 | coin | 1 | — | bâtiment |
| `521/L` | Large building with outline | batiment | libre | — | — | — | — | — | contour de bâtiment : sans effet propre |
| `521/P` | Building, minimum size | batiment | infranchissable | — | — | ponctuel | 2 | — | bâtiment, taille minimale |
| `522/A` | Canopy with outline | batiment | libre | V1 | — | coin | 2 | — | auvent, passage couvert : franchissable |
| `522/L` | Canopy with outline | batiment | libre | — | — | — | — | — | contour d'auvent : sans effet propre |
| `523/L` | Ruin | batiment | libre | — | — | coin | 3 | — | ruine |
| `523/P` | Ruin, minimum size | batiment | libre | — | — | ponctuel | 3 | — | ruine, taille minimale |
| `524/P` | High tower | ouvrage | libre | — | — | ponctuel | 3 | — | grande tour |
| `525/P` | Small tower | ouvrage | libre | — | — | ponctuel | 3 | — | petite tour, affût |
| `526/P` | Cairn | ouvrage | libre | — | — | ponctuel | 4 | — | cairn, borne, petit monument |
| `527/P` | Fodder rack | ouvrage | libre | — | — | ponctuel | 3 | — | mangeoire |
| `528/L` | Prominent line feature | ouvrage | lent (2 s) | — | L2* | coin | 3 | — | élément linéaire particulier |
| `529/L` | Prominent impassable line feature | ouvrage | infranchissable | — | L2* | coin | 3 | — | élément linéaire infranchissable |
| `530/P` | Prominent man-made feature – ring | ouvrage | libre | — | — | ponctuel | 3 | — | élément particulier (cercle) |
| `531/P` | Prominent man-made feature – x | ouvrage | libre | — | — | ponctuel | 3 | — | élément particulier (croix) |
| `532/L` | Stairway | chemin | libre | V3 | L1 | extremite | 2 | — | escalier |
### 2.2 — ISSprOM 2019 (cartes de sprint, 1:4 000 et 1:3 000)

| Clé | Nom de référence | Famille | Passabilité | Vitesse | Ligne | Site | Évid. | Drapeaux | Remarque |
|-----|------------------|---------|-------------|---------|-------|------|-------|----------|----------|
| `101/L` | Contour | relief | libre | — | — | — | — | courbe | courbe de niveau ; ligne de relief en phase 10 |
| `101/P` | Slope line, contour | mise_en_page | libre | — | — | — | — | — | tiret de pente : ignoré |
| `102/L` | Index contour | relief | libre | — | — | — | — | courbe | courbe maîtresse |
| `102/P` | Slope line, index contour | mise_en_page | libre | — | — | — | — | — | tiret de pente : ignoré |
| `103/L` | Form line | relief | libre | — | — | — | — | courbe | courbe de forme |
| `103/P` | Slope line, form line | mise_en_page | libre | — | — | — | — | — | tiret de pente : ignoré |
| `104/L` | Earth bank | relief | lent (3 s) | — | L2 | extremite | 3 | — | talus |
| `105/L` | Small earth wall | relief | lent (2 s) | — | L2 | extremite | 3 | — | levée de terre |
| `107/L` | Erosion gully or trench | relief | lent (3 s) | — | L3* | extremite | 3 | — | ravine |
| `108/L` | Small erosion gully | relief | libre | — | L3* | extremite | 3 | — | petite ravine |
| `109/P` | Small knoll | relief | libre | — | — | ponctuel | 4 | — | petite butte |
| `110/P` | Small elongated knoll | relief | libre | — | — | ponctuel | 4 | — | butte allongée |
| `111/P` | Small depression | relief | libre | — | — | ponctuel | 4 | — | petite dépression |
| `112/P` | Pit or hole | relief | libre | — | — | ponctuel | 4 | — | trou |
| `113/A` | Broken ground | relief | libre | V2 | — | — | — | — | terrain accidenté : peu d'effet sur la vitesse (ISOM 2017-2, 113) |
| `113/P` | Broken ground, single dot | mise_en_page | libre | — | — | — | — | — | point de trame : ignoré |
| `115/P` | Prominent landform feature | relief | libre | — | — | ponctuel | 4 | — | élément de relief particulier |
| `201/L` | Impassable cliff | roche | infranchissable | — | L3* | extremite | 3 | danger | falaise infranchissable |
| `201/P` | Impassable cliff, minimum size | roche | infranchissable | — | — | ponctuel | 4 | danger | falaise infranchissable, taille minimale |
| `202/L` | Passable rock face, small (rounded ends, no tags) | roche | lent (10 s) | — | L3* | extremite | 3 | — | falaise / paroi franchissable |
| `202/P` | Passable rock face, minimum size | roche | libre | — | — | ponctuel | 4 | — | falaise franchissable, taille minimale |
| `203/P` | Rocky pit or cave (without a distinct entrance) | roche | libre | — | — | ponctuel | 4 | — | trou rocheux, grotte |
| `204/P` | Boulder | roche | libre | — | — | ponctuel | 4 | — | rocher |
| `205/P` | Large boulder | roche | libre | — | — | ponctuel | 4 | — | gros rocher |
| `206/A` | Gigantic boulder or rock pillar | roche | infranchissable | — | — | petite_surface | 3 | — | rocher gigantesque, pilier rocheux |
| `207/P` | Boulder cluster | roche | libre | — | — | ponctuel | 4 | — | groupe de rochers |
| `208/A` | Boulder field | roche | libre | V2 | — | — | — | — | champ de blocs |
| `208/P` | Boulder field, single triangle | mise_en_page | libre | — | — | — | — | — | triangle de trame : ignoré |
| `210/A` | Stony ground | roche | libre | V3 | — | — | — | — | sol pierreux, course ralentie (60-80 %) |
| `210/P` | Stony ground, single dot | mise_en_page | libre | — | — | — | — | — | point de trame : ignoré |
| `213/A` | Open sandy ground | roche | libre | V3 | — | — | — | — | sol sablonneux (< 80 %) |
| `214/A` | Bare rock | roche | libre | V2 | — | — | — | — | dalle rocheuse |
| `301/A` | Uncrossable body of water (full colour) | eau | infranchissable | — | L2 | coin | 2 | — | eau infranchissable ; la rive sert de ligne |
| `301/L` | Uncrossable body of water (full colour) | eau | libre | — | — | — | — | — | trait de rive : sans effet propre (la surface porte l'obstacle) |
| `302/A` | Crossable body of water | eau | libre | V4 | L2 | petite_surface | 2 | — | eau peu profonde, franchissable (surface : la vitesse porte le ralentissement) |
| `302/L` | Crossable body of water | eau | libre | — | — | — | — | — | trait de rive : sans effet propre |
| `303/P` | Waterhole | eau | libre | — | — | ponctuel | 4 | — | trou d'eau |
| `305/L` | Small crossable watercourse | eau | lent (2 s) | — | L2 | jonction | 3 | — | petit cours d'eau franchissable |
| `306/L` | Minor / seasonal watercourse | eau | libre | — | L3 | jonction | 3 | — | rigole, cours d'eau saisonnier |
| `307/A` | Uncrossable marsh | eau | infranchissable | — | L3* | — | — | — | marais infranchissable |
| `307/L` | Uncrossable marsh | eau | libre | — | — | — | — | — | contour de marais : sans effet propre |
| `308/A` | Marsh | eau | libre | V3 | L3* | petite_surface | 3 | — | marais |
| `308/P` | Marsh, minimum size | eau | libre | — | — | ponctuel | 4 | — | marais, taille minimale |
| `309/L` | Narrow marsh | eau | libre | — | L3* | extremite | 3 | — | marais étroit |
| `310/A` | Indistinct marsh | eau | libre | V2 | — | — | — | — | marais peu visible |
| `310/P` | Indistinct marsh, minimum size | eau | libre | — | — | ponctuel | 4 | — | marais peu visible, taille minimale |
| `311/P` | Small fountain or well | eau | libre | — | — | ponctuel | 4 | — | puits, fontaine |
| `312/P` | Spring | eau | libre | — | — | ponctuel | 4 | — | source |
| `313/P` | Prominent water feature | eau | libre | — | — | ponctuel | 4 | — | élément d'eau particulier |
| `401/A` | Open land | vegetation | libre | V1 | L2 | coin | 2 | ouvert | terrain découvert ; lisière = ligne nette |
| `402/A` | Open land with scattered trees | vegetation | libre | V1 | L3 | — | — | — | terrain découvert, arbres dispersés |
| `403/A` | Rough open land | vegetation | libre | V2 | L3 | coin | 3 | ouvert | terrain découvert encombré |
| `404/A` | Rough open land with scattered trees | vegetation | libre | V2 | — | — | — | — | découvert encombré, arbres dispersés |
| `405/A` | Forest | vegetation | libre | V2 | — | — | — | — | forêt (souvent : absence d'objet) |
| `406/A` | Vegetation: slow running | vegetation | libre | V3 | — | — | — | — | course ralentie |
| `406/L` | Vegetation: slow running, minimum width | vegetation | lent (4 s) | — | L3 | — | — | — | bande de végétation lente, largeur minimale |
| `407/A` | Vegetation: slow running, good visibility | vegetation | libre | V3 | — | — | — | — | course ralentie, bonne visibilité |
| `408/A` | Vegetation: walk | vegetation | libre | V4 | — | — | — | — | marche |
| `408/L` | Vegetation: walk, minimum width | vegetation | lent (10 s) | — | L3 | — | — | — | bande de végétation dense, largeur minimale |
| `409/A` | Vegetation: walk, good visibility | vegetation | libre | V4 | — | — | — | — | marche, bonne visibilité |
| `410/A` | Impassable vegetation | vegetation | infranchissable | — | — | — | — | — | végétation INFRANCHISSABLE en ISSprOM 2019 |
| `410/L` | Impassable vegetation, minimum width (hedge) | vegetation | infranchissable | — | L2 | coin | 3 | — | haie infranchissable |
| `412/A` | Cultivated land | vegetation | libre | V2 | L3 | coin | 3 | ouvert, saisonnier | culture : peut être interdite selon la saison → à confirmer par le traceur |
| `412/L` | Cultivated land | vegetation | libre | — | — | — | — | — | contour : sans effet propre |
| `413/A` | Orchard | vegetation | libre | V2 | L3 | — | — | — | verger |
| `414/A` | Vineyard or similar | vegetation | libre | V3 | L3 | — | — | directionnel | vigne |
| `415/L` | Distinct cultivation boundary | vegetation | libre | — | L3 | coin | 3 | — | limite de culture nette |
| `416/L` | Distinct vegetation boundary | vegetation | libre | — | L3 | coin | 3 | — | limite de végétation nette |
| `417/P` | Prominent large tree | vegetation | libre | — | — | ponctuel | 3 | — | arbre remarquable |
| `418/P` | Prominent bush or small tree | vegetation | libre | — | — | ponctuel | 4 | — | buisson ou petit arbre remarquable |
| `419/P` | Prominent vegetation feature | vegetation | libre | — | — | ponctuel | 4 | — | élément de végétation particulier |
| `501/A` | Paved area, light traffic, with border | chemin | libre | V1 | L1 | coin | 2 | ouvert | zone pavée |
| `501/L` | Paved area, light traffic, with border | chemin | libre | — | — | — | — | — | marche ou bord de zone pavée ; chemin pavé si trait ≥ 0,30 mm (voir §2.5) |
| `505/L` | Unpaved footpath or track, footprint: 1.4 m | chemin | libre | V1 | L1 | jonction | 2 | — | sentier ou chemin non pavé |
| `506/L` | Small unpaved footpath or track | chemin | libre | V1 | L1 | jonction | 2 | — | sentier |
| `507/L` | Less distinct small path | chemin | libre | V2 | L2 | jonction | 3 | — | sentier peu visible |
| `508/L` | Narrow ride | chemin | libre | V2 | L2 | jonction | 3 | — | layon |
| `509/A` | Railway | ouvrage | libre | — | — | — | — | voie_ferree | emprise de voie ferrée : à confirmer |
| `509/L` | Railway | ouvrage | libre | — | L1 | — | — | voie_ferree | voie ferrée, tramway : traversée à confirmer |
| `510/L` | Power line, cableway or skilift | ouvrage | libre | — | L1 | — | — | — | ligne électrique, téléphérique : aérien, sans effet au sol |
| `511/L` | Major power line | ouvrage | libre | — | L1 | — | — | — | ligne électrique majeure |
| `512/L` | Bridge, one side | ouvrage | ouvre | — | — | extremite | 2 | multi_niveaux | pont, passage souterrain, tunnel |
| `513/L` | Passable wall | ouvrage | lent (4 s) | — | L1 | coin | 2 | — | mur franchissable, mur de soutènement franchissable |
| `515/L` | Impassable wall | ouvrage | infranchissable | — | L1 | coin | 2 | — | mur infranchissable |
| `516/L` | Passable fence or railing | ouvrage | lent (4 s) | — | L1 | coin | 2 | — | clôture ou barrière franchissable |
| `518/L` | Impassable fence or railing | ouvrage | infranchissable | — | L1 | coin | 2 | — | clôture infranchissable |
| `519/P` | Crossing point (optional) | ouvrage | ouvre | — | — | ponctuel | 3 | — | point de passage |
| `520/A` | Area that shall not be entered | interdit | interdit | — | — | — | — | — | zone interdite d'accès (olive) |
| `520/L` | Area that shall not be entered, boundary line | interdit | libre | — | — | — | — | — | trait de limite : sans effet propre (la surface porte l'interdit) |
| `521/A` | Building | batiment | infranchissable | — | L1 | coin | 1 | — | bâtiment |
| `521/L` | Building | batiment | libre | — | — | — | — | — | contour de bâtiment : sans effet propre |
| `521/P` | Building, minimum size | batiment | infranchissable | — | — | ponctuel | 2 | — | bâtiment, taille minimale |
| `522/A` | Canopy | batiment | libre | V1 | — | coin | 2 | — | auvent, passage couvert : franchissable |
| `522/L` | Canopy | batiment | libre | — | — | — | — | — | contour d'auvent : sans effet propre |
| `522/P` | Pillar | batiment | infranchissable | — | — | — | — | — | pilier : obstacle, pas un site |
| `524/P` | High tower | ouvrage | libre | — | — | ponctuel | 3 | — | grande tour |
| `525/P` | Small tower | ouvrage | libre | — | — | ponctuel | 3 | — | petite tour, affût |
| `526/P` | Cairn, memorial, small monument or boundary stone | ouvrage | libre | — | — | ponctuel | 4 | — | cairn, borne, petit monument |
| `527/P` | Fodder rack | ouvrage | libre | — | — | ponctuel | 3 | — | mangeoire |
| `528/L` | Prominent line feature | ouvrage | lent (2 s) | — | L2* | coin | 3 | — | élément linéaire particulier |
| `529/L` | Prominent impassable line feature | ouvrage | infranchissable | — | L2* | coin | 3 | — | élément linéaire infranchissable |
| `530/P` | Prominent man-made feature – ring | ouvrage | libre | — | — | ponctuel | 3 | — | élément particulier (cercle) |
| `531/P` | Prominent man-made feature – x | ouvrage | libre | — | — | ponctuel | 3 | — | élément particulier (croix) |
| `532/L` | Stairway, footprint: 1.6 m | chemin | libre | V3 | L1 | extremite | 2 | — | escalier |
### 2.3 — Clés précises ISSprOM 2019

Clés précises (à ajouter si les sous-numéros de la carte sont ceux de la norme ; sinon
l'indice de nom du §5 fait le même travail) :

| Clé | Effet |
|-----|-------|
| `501.2/A`, `501.12/A` | drapeau `multi_niveaux` (« Paved area in multilevel structures ») |
| `501.10/A`, `501.11/A`, `501.12/A`, `501.16/L` à `501.19/L` | drapeau `circulation` (« heavy traffic ») |
| `512.2/L` | passage souterrain ou tunnel : `ouvre`, drapeau `multi_niveaux` |
| `104.1/L` | talus très haut : comme `104/L`, pénalité 6 s |

### 2.4 — Sous-symboles et numéros hors norme

Une carte porte souvent des sous-numéros (`521.3`, `520.1`, `501.12`) : la clé générale du numéro
principal s'applique, sauf clé précise (§1, point 3). Un numéro absent de la table de la norme
détectée reçoit d'abord l'indice de son nom (§5) ; à défaut, il prend le statut « inconnu » et il
est montré au traceur (phase 2) — jamais interprété d'office.

### 2.5 — Lignes 501 et 529 : précision par la largeur de trait

Une ligne de numéro principal 501 (ISOM 2017-2,
ISSprOM 2019) ou 529 (ISOM 2000, ISSOM 2007) est :

- un **chemin pavé** — famille `chemin`, V1, ligne L1, site `jonction`, évidence 2 — si la largeur de
  son trait principal est d'au moins 0,30 mm (`line_width_mm` du paquet de carte) ;
- un simple **bord ou une marche** de zone pavée, sans effet, sinon.

Les jeux de référence portent en effet sous ces numéros à la fois des traits de bord et des chemins
pavés dessinés en ligne (ISSprOM 2019 : « Paved area, light traffic, footprint 1.4 m » à « 4 m »).

### 2.6 — Symboles techniques (600 à 699)

Toutes normes : lignes du nord magnétique, croix de repérage, points cotés. Statut `ignore`.

### 2.7 — Surimpression (700 à 799) : seuls certains ont un effet

Un fichier de carte peut contenir des symboles de parcours. Ils ne décrivent pas le terrain, sauf
ceux-ci, qui valent pour **tout** circuit tracé sur la carte :

| Norme | Clé | Nom de référence | Passabilité |
|-------|-----|------------------|-------------|
| ISOM 2017-2, ISSprOM 2019 | `708/L` | Out-of-bounds boundary | `interdit` (ligne) |
| ISOM 2017-2, ISSprOM 2019 | `709/A` | Out-of-bounds area | `interdit` |
| ISOM 2017-2, ISSprOM 2019 | `710/P`, `710/L` | Crossing point, crossing section | `ouvre` |
| ISOM 2017-2 | `711/L`, `711/P` | Out-of-bounds route | `interdit` (ligne) |
| ISSprOM 2019 | `714/A`, `714/P` | Temporary construction or closed area | `interdit` |
| ISOM 2000, ISSOM 2007 | `707/L` | Uncrossable boundary | `interdit` (ligne) |
| ISOM 2000, ISSOM 2007 | `708/P`, `708/L` | Crossing point, crossing section | `ouvre` |
| ISOM 2000, ISSOM 2007 | `709/A` | Out-of-bounds area | `interdit` |
| ISOM 2000 | `710/A` | Dangerous area | `interdit` |
| ISOM 2000 | `711/P` | Forbidden route | `interdit` |
| ISSOM 2007 | `714/A` | Temporary construction or closed area | `interdit` |

Les autres numéros 700–799 (départ, poste, numéro, ligne, arrivée, itinéraire balisé, secours,
ravitaillement) ont le statut `ignore` dans la lecture de la carte ; la phase 9 les relit comme
**circuits** pour constituer le corpus.

## 3. Lignes, évidence, drapeaux

### 3.1 Les trois types de lignes de la FFCO

Source : *Traçage – Aspects pratiques* (FFCO), « Types de lignes et niveaux de difficulté », p. 8 et
p. 10 du PDF du dépôt.

| Classe | Texte FFCO | Symboles (ISOM 2017-2) |
|--------|------------|------------------------|
| **L1** | « les lignes les plus familières au pratiquant débutant et très visibles qui guident facilement le déplacement : route forestière, chemin d'exploitation, chemin, sentier, pare-feu, clôtures, mur, rivière, ligne électrique, voie ferrée, bâtiment » | 501–506, 532, 513, 515, 516, 518, 304, 510, 511, 509, bord de 521 |
| **L2** | « des lignes dont la représentation sous forme de pointillés ou de surfaces entourées d'un trait continu […] permettent un suivi aisé : sentier peu visible, talus bien marqué, fossé très visible, ruisseau, muret, lisière de forêt, haie, layon, levée de terre, tour de lac, étang » | 507, 508, 104, 215, 305, 105, 410 en ligne, bord de 401, bord de 301 et 302 |
| **L3** | « ces lignes séparent des zones différenciées par la couleur sur la carte : limite de végétation entre zones boisées et zones déboisées ou champs, pénétrabilités différentes mais nettes […], limite de clairière en forêt, mais aussi des fossés intermittents, murs en ruine » | 416, 415, 306, 514, bords de 402, 403, 412–414 |

Le même document précise (p. 7) que pour les plus jeunes « ces mains courantes ne sont pas seulement
des lignes mais aussi des surfaces "non boisées" où la visibilité est importante » : c'est le
drapeau `ouvert`.

Non cités par la FFCO, classés par ce plan (astérisque dans les tables) : falaises (L3\*), ravines
(L3\*), levée de terre ruinée (L3\*), clôture ruinée (L3\*), bords de marais (L3\*), éléments linéaires
particuliers 528 et 529 (L2\*). À soumettre au traceur en phase 4 (revue de calage).

### 3.2 Évidence d'un site

Sources : *Traçage – Principes* (FFCO) §3.5.1, p. 9 — « poste facile : les surfaces (grande
clairière, mare, sommet…) ; poste moyen : les coudes de lignes (chemin, fossé, ruisseau, limite de
végétation…) ; poste difficile : les points (rocher, trou, butte…) » — et *Méthode fédérale* T1, p. 4 —
« Choisir des postes faciles : bâtiment, jonction ou croisement de chemins ».

| Évidence | Définition | Exemples |
|----------|------------|----------|
| 1 — évident | Bâtiment ; jonction ou croisement de deux lignes L1. | coin de bâtiment sur la rue, carrefour de chemins |
| 2 — facile | Surface nette ; coude ou extrémité d'une ligne L1 ; jonction d'une ligne L1 avec une ligne L2 ; pont. | coin de clairière, mare, coude de chemin, chemin × ruisseau, coin de clôture |
| 3 — moyen | Coude, extrémité ou jonction de lignes L2 et L3 ; élément ponctuel haut ou isolé. | extrémité de talus, angle de limite de végétation, tour, mangeoire, arbre remarquable |
| 4 — difficile | Les points. | rocher, butte, dépression, trou, source |

L'évidence des tables est une valeur **de base**. La phase 3 la corrige par le contexte : +1 (plafond
4) quand au moins trois éléments de même nature se trouvent dans un rayon de 30 m en sprint, 60 m en
forêt. La jonction de deux lignes est calculée par la géométrie, pas lue dans la table.

### 3.3 Drapeaux

| Drapeau | Effet |
|---------|-------|
| `ouvert` | Surface dégagée, bonne visibilité : vaut ligne directrice pour les niveaux vert et bleu ; les « sauts » du niveau bleu (Méthode fédérale T6) n'y sont permis que là. |
| `saisonnier` | Culture : franchissable par défaut, **signalée** au traceur, qui peut la passer en `interdit` pour sa date de course. |
| `voie_ferree`, `circulation` | Traversée à confirmer par le traceur ; tant qu'il n'a pas répondu, traitée en `infranchissable`. |
| `multi_niveaux` | Pont, passage souterrain, parking à étages : la grille à plat ne sait pas représenter deux niveaux. Les sites y sont refusés et les jambes qui les traversent sont signalées, jusqu'à modélisation (hors plan). |
| `directionnel` | Végétation ou vigne dont la vitesse dépend du sens : traitée à la vitesse de la classe de base. |
| `danger` | Falaise infranchissable, champ de tir : affiché dans le rapport de contrôle. |
| `courbe` | Courbe de niveau : sans effet avant la phase 10. |

## 4. Anciennes normes : génération et exceptions

Les tables `isom2000.json` et `issom2007.json` sont **générées** : pour chaque symbole ancien,
`ancien code → table de correspondance d'OpenOrienteering (.crt) → clé de la norme actuelle → rôle`.
Simulation faite le 10 novembre 2026 sur les fichiers d'OpenOrienteering :

| Norme | Couples (numéro, type) | Générés sans ambiguïté | Sans correspondance | Ambigus |
|-------|------------------------|------------------------|---------------------|---------|
| ISOM 2000 | 109 | 101 | 2 | 6 |
| ISSOM 2007 | 99 | 94 | 2 | 3 |

Le générateur doit **refuser** de produire une clé générale quand les sous-symboles d'un même couple
aboutissent à des rôles différents ; chaque cas est alors réglé par une ligne de ce tableau.

### 4.1 Exceptions ISOM 2000

| Clé | Nom de référence | Décision | Motif |
|-----|------------------|----------|-------|
| `411/A` | Forest runnable in one direction (3 variantes) | `vegetation`, V4, drapeau `directionnel` | Les variantes renvoient à V3, V4, V5 : valeur médiane. |
| `501/A`, `501/L` | Motorway | `chemin`, `infranchissable`, drapeau `circulation` | Autoroute : jamais un itinéraire ; à confirmer par le traceur. |
| `502/L`, `503/L` | Major road, minor road (dont « under construction ») | comme le symbole de base : `chemin`, V1, L1 | Variante sans correspondance. |
| `530/L` | Ruin (dont « no dashes ») | comme `523/L` ISOM 2017-2 | Variante sans correspondance. |
| `531/L` | Firing range | `ouvrage`, `libre`, drapeau `danger`, statut « à confirmer » | Aucune correspondance. |
| `532/P` | Grave | `ouvrage`, site `ponctuel`, évidence 4 | Aucune correspondance. |

À vérifier par test après génération (correspondances justes mais contre-intuitives) :
`526/A` → bâtiment, `infranchissable` ; `527/A` (Settlement) et `528/A` (Permanently out of bounds) →
`interdit` ; `521/L` (High stone wall) et `524/L` (High fence) → `infranchissable` ; `529/A` → zone
pavée ; `302/A` (Pond) → eau `infranchissable` ; `410/A` → V5 **franchissable** ; `112/P` → petite
butte ; `206/P` → rocher ; `537/P` → cairn.

### 4.2 Exceptions ISSOM 2007

| Clé | Nom de référence | Décision | Motif |
|-----|------------------|----------|-------|
| **`410/A`** | Vegetation: very difficult to run | `vegetation`, V5, **franchissable** | **Piège** : la correspondance renvoie à 410 d'ISSprOM 2019, qui est *infranchissable*. En ISSOM 2007, l'infranchissable est 421. |
| **`410/L`** | Vegetation, very difficult to run, minimum width (hedge) | `vegetation`, `lent (15 s)`, L2 | Même piège. |
| `526/A` | Building (526.1) | `batiment`, `infranchissable`, L1, site `coin`, évidence 1 | Clé générale = le sens le plus restrictif. |
| `526.2/A` | Canopy | `batiment`, `libre`, V1, site `coin`, évidence 2 | Clé précise : auvent franchissable. |
| `526/P` | Building, minimum size | `batiment`, `infranchissable`, site `ponctuel`, évidence 2 | |
| `526.3/P` | Pillar | `batiment`, `infranchissable`, pas de site | Clé précise. |
| `529/L` | Paved road ; step or edge of paved area ; stairway | règle de largeur de trait du §2.5 | Trois sens sous le même numéro. |
| `519/A` | Passable wall, plan shape | `ouvrage`, `libre`, V4 | Aucune correspondance. |
| `521/A` | Impassable wall, plan shape | `ouvrage`, `infranchissable` | Aucune correspondance. |

À vérifier par test après génération : `528/A` → `interdit` ; `421/A` et `421/L` → `infranchissable` ;
`304/A` → eau `infranchissable` ; `305/A` → eau franchissable V4 ; `521/L` → mur `infranchissable` ;
`524/L` → clôture `infranchissable` ; `522/L` → clôture `lent` ; `519/L` → mur `lent` ; `518/L` →
`ouvre`, `multi_niveaux` ; `512/L` → `ouvre`, `multi_niveaux` ; `415/A` → drapeau `saisonnier` ;
`202/A` → rocher gigantesque `infranchissable`.

## 5. Indices de nom

Pour les symboles dont le numéro est absent de la norme retenue (jeux « maison »), le nom sert
d'indice. Fichier `symbols/name_hints.json` : liste ordonnée d'expressions régulières, insensibles à
la casse et aux accents, appliquées au nom **tel quel** puis au nom **tronqué à 32 caractères**
(OCAD tronque les noms : relevé par lidar-o, `scripts/mappings/ffco_fr.yaml`).

| Ordre | Expression (français \| anglais) | Modèle de rôle | Appliqué d'office ? |
|-------|----------------------------------|----------------|---------------------|
| 1 | `interdit\|defendu\|priv[ée]\|hors.?limite\|acces.*interdit` \| `out.?of.?bounds\|shall not be entered\|forbidden\|private` | `interdit` | **oui** (prudence) |
| 2 | `infranchissable` \| `impassable\|uncrossable` | `infranchissable` | oui |
| 3 | `b[aâ]timent\|maison\|construction` \| `building\|house` | `batiment` | non |
| 4 | `auvent\|pr[ée]au\|passage couvert` \| `canopy` | `auvent` | non |
| 5 | `pav[ée]\|goudron\|bitume\|rev[êe]tu` \| `paved\|tarmac\|asphalt` | `zone_pavee` | non |
| 6 | `peu visible\|peu net` \| `less distinct\|indistinct` | `chemin_peu_visible` | non |
| 7 | `route\|chemin\|sentier\|piste` \| `road\|track\|path` | `chemin_net` | non |
| 8 | `cl[oô]ture\|mur\|grillage\|palissade` \| `fence\|wall\|railing` | `ligne_nette` | non |
| 9 | `limite\|lisi[èe]re\|foss[ée]\|layon` \| `boundary\|ditch\|ride` | `ligne_peu_nette` | non |
| 10 | `d[ée]couvert\|pelouse\|prairie\|pr[ée]\b` \| `open land\|lawn\|meadow` | `vegetation_V1` | non |
| 11 | `course ralentie\|course lente` \| `slow running` | `vegetation_V3` | non |
| 12 | `marche` \| `walk\|difficult to run` | `vegetation_V4` | non |
| 13 | `progression difficile\|lutte` \| `fight\|very difficult` | `vegetation_V5` | non |
| 14 | `courbe` \| `contour\|form line` | `courbe_de_niveau` | non |
| 15 | `multi.?niveau\|plusieurs niveaux\|souterrain\|tunnel\|passerelle` \| `multilevel\|underpass\|tunnel` | drapeau `multi_niveaux` (s'ajoute au rôle) | oui |
| 16 | `circulation` \| `heavy traffic` | drapeau `circulation` | oui |

L'ordre compte : « Végétation infranchissable » doit donner `infranchissable` (règle 2) avant toute
règle de végétation ; « Zone interdite » donne `interdit` (règle 1) avant tout le reste.

Jeu d'essai : les noms réels relevés sur les cartes FFCO par lidar-o
(`scripts/mappings/ffco_fr.yaml`, `isom_fr.yaml`), dont « Terrain boisé,course ralentie »,
« Zone découv.+ arbres dispersés », « Végétation, progression difficil », « Terrain découvert
encombré avec » — chacun doit recevoir l'indice de son groupe d'origine (test de l'étape 2.5).

## 6. Ce que cette annexe ne tranche pas

- La numérotation **réelle** des sous-symboles dans les fichiers OCAD du traceur (la sonde de
  l'étape 2.3.0 la relève).
- Les pénalités de franchissement en secondes : valeurs de départ, calées en phase 9.
- Le classement des lignes marquées d'un astérisque : soumis au traceur en phase 4.
