# LRI v2 — Conclusion validation expérimentale

**Date :** 2026-05-31  
**Dataset :** 6 cartes forêt (n=168 jambes valides) + 1 carte sprint (Caen, n=46)

---

## 1. Résultats forêt

### Signal global

| Métrique | Valeur |
|---|---|
| ρ(PC1, label) combiné | +0.166 (p=0.032) |
| AUC(PC1) | 0.604 ± 0.095 |
| AUC(decision_pressure) | 0.586 ± 0.110 |
| Gain AUC(PC1+dp) vs AUC(dp) | +0.009 |

Signal significatif à p=0.032 mais faible (ρ=0.166). PC1 n'apporte aucune information prédictive au-delà de decision_pressure (gain +0.009, non significatif).

### Hétérogénéité inter-cartes

| Carte | ρ(PC1) | p | delta PC1 (att−sui) |
|---|---|---|---|
| airelles | +0.182 | 0.407 | +2.3 |
| llose | +0.204 | 0.255 | +1.9 |
| montmirel | +0.137 | 0.439 | +2.6 |
| cerisy | −0.270 | 0.157 | −3.5 ← inversé |
| grochot | +0.444 | 0.020 * | +4.1 |
| steanne | +0.077 | 0.733 | +1.5 |

Aucune carte individuelle n'atteint p < 0.05 sauf Grochot. Le signal combiné est significatif, avec une contribution particulièrement marquée de Grochot, seule carte présentant un signal robuste individuellement (pinède landaise, terrain atypique).

### Anomalie Cerisy

Les jambes annotées "attaque" à Cerisy ont un HANDRAIL_FOLLOW très élevé (0.629 vs 0.075 à Grochot, p=0.085) et sont plus courtes (307m vs 419m, p=0.006). À Cerisy, les points d'attaque sont typiquement atteints via une main courante — le modèle ISOM les classe comme "suivi", d'où le delta PC1 négatif. C'est un désaccord de définition du label en forêt normande dense, pas un défaut de conception.

### Intercorrélations

Sur toutes les cartes : corr(PC1, ATTACK_POINT) ≈ +0.75, corr(PC1, decision_pressure) ≈ +0.78. PC1 est fortement corrélé à ATTACK_POINT et à decision_pressure, ce qui suggère qu'il capture majoritairement la même information. Aucun gain prédictif exploitable n'a été observé lors de l'ajout simultané de PC1 et decision_pressure.

---

## 2. Résultats sprint (Caen, n=46)

| Cible | ρ(PC1) | p | ρ(dp) | p |
|---|---|---|---|---|
| route_count | −0.227 | 0.129 | +0.095 | 0.532 |
| route_impact | −0.159 | 0.292 | +0.167 | 0.266 |
| count+impact | −0.184 | 0.220 | +0.130 | 0.389 |

Régression R²(PC1) = −0.20, R²(dp) = −0.25. Aucun signal.

PC1 est construit sur des features ISOM forêt — il ne capture pas le concept de choix d'itinéraire sprint. Ce résultat est attendu, pas une disqualification de PC1.

### Features réseau OSM (enrich_sprint_legs.py, valid_graph_ratio = 1.000)

| Feature | Cible | ρ | p | p_perm |
|---|---|---|---|---|
| route_diversity (Jaccard) | route_count | +0.168 | 0.264 | 0.286 |
| route_diversity (Jaccard) | route_impact | +0.161 | 0.284 | 0.285 |
| **path_length_ratio** | **route_count** | **+0.546** | **0.0001** | **0.001** |
| **path_length_ratio** | **route_impact** | **+0.493** | **0.0005** | **0.002** |
| decision_points [explor.] | route_count | +0.558 | 0.0001 | 0.001 |
| decision_points [explor.] | route_impact | +0.504 | 0.0004 | 0.001 |

`route_diversity` (Jaccard topologique) ne capte pas le concept : la diversité des chemins en termes d'arêtes partagées n'est pas ce que les orienteurs appellent "choix". C'est la similarité de longueur (`path_length_ratio`) qui est opérationnelle — quand les deux meilleures routes ont des longueurs proches, le dilemme est réel et les annotateurs le perçoivent. Signal robuste (p_perm ≤ 0.002).

`decision_points` montre un signal similaire mais dépend du seuil 30° et de la simplification du graphe — à traiter comme confirmatoire, pas central.

**Conclusion sprint :** H1 partiellement confirmée. `path_length_ratio` est une feature opérationnelle viable pour le scoring sprint. Elle peut être intégrée au terme fitness L ou à un nouveau terme M sprint-spécifique.

---

## 3. Décision produit

### Ce que l'expérience établit

- **PC1 ≠ bruit pur.** Le signal forêt est significatif (p=0.032) et la séparation PC1(attaque) > PC1(suivi) est cohérente sur 5/6 cartes.
- **PC1 ≠ indicateur suffisamment robuste.** Le signal ne généralise pas de façon cohérente entre cartes. L'hétérogénéité est réelle, pas uniquement due au faible n.
- **PC1 ≠ meilleur candidat opérationnel.** decision_pressure (= ATTACK_POINT sur ces cartes, SAFETY_RECOVERY étant constant) prédit aussi bien avec une interprétation plus directe.
- **Le facteur limitant n'est plus la taille du dataset.** Le passage de n=56 à n=168 a permis de faire émerger un signal global significatif mais n'a pas réduit l'hétérogénéité inter-cartes. La principale limite est désormais la définition des labels : "attaque" et "suivi" ne sont pas équivalents entre types de terrains.

### Recommandation

**Court terme — décision produit :** utiliser `decision_pressure` comme proxy de qualité opérationnelle. Corrélation avec le jugement expert démontrée sur airelles (ρ=+0.450, p=0.031). Plus interprétable, moins sensible à la normalisation PCA.

**Moyen terme — si LRI v2 doit être publié ou généralisé :** adresser la limite de généralisation inter-cartes avant tout. La principale piste est la définition des labels : "attaque" et "suivi" ne sont pas équivalents entre un terrain ouvert (Grochot, Landes) et une forêt dense normande (Cerisy). Une annotation avec des critères explicites par type de terrain serait nécessaire.

**Sprint :** PC1 et dp ne capturent pas le choix d'itinéraire. Si ce concept doit être intégré au système, un feature engineering spécifique ISSprOM (connectivité du réseau de rues, nb d'alternatives routières) est requis.

---

## 4. Périmètre du dataset

| Carte | Type | n valides | Note |
|---|---|---|---|
| airelles | forêt RunningRaid | 23 | 45% uncertain |
| llose | forêt RunningRaid | 33 | 21% uncertain |
| montmirel | forêt Perche | 34 | 19% uncertain, chemins denses |
| cerisy | forêt normande | 29 | signal inversé — défini hors-scope |
| grochot | pinède landaise | 27 | seul signal robuste |
| steanne | forêt normande | 22 | 48% uncertain, n_attaque=5 |
| caen | sprint ISSprOM | 46 | labels count×impact |
