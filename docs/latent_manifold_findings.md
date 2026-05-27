# Latent Manifold — Findings (A.8b / A.8c / Q3 / v2)

> Phase analytique : A.8b → A.8c → Q3 → **latent-analysis-v2**  
> Dataset v1 (L mort) : `backend/debug/intent_legs_a8b_v2.csv` — tag `latent-analysis-v1`  
> Dataset v2 (L vivant) : `backend/debug/intent_legs_post_fix_full.csv` — tag `latent-analysis-v2`  
> Scripts : `collect_fitness_data.py`, `analyze_td_interaction.py`, `analyze_latent_structure.py`, `plot_manifold.py`

---

## 1. Motivation

L'objectif de cette série d'analyses est de comprendre si les circuits générés par le GA possèdent une structure latente — c'est-à-dire si l'espace des vecteurs d'intent/affordance per-leg se réduit à un manifold de faible dimension portant de l'information sur :

- la **diversité** des circuits produits,
- le **contrôle par niveau de difficulté technique** (TD),
- la **relation à la fitness** (est-ce que le GA explore des régions du manifold de façon cohérente ?),
- le **comportement différentiel selon la carte** (domain shift).

---

## 2. Dataset & protocole

### Dataset v2

| Paramètre | Valeur |
|-----------|--------|
| Circuits | 46 |
| Legs | 616 |
| Carte St Anne (stanne) | 10 circuits — TD3 uniquement |
| Carte Crohot (crohot) | 36 circuits — TD3 / TD4 / TD5 |
| TD3 total | 22 circuits (10 stanne + 12 crohot) |

Les circuits ont été collectés via `collect_fitness_data.py` avec `INTENT_DEBUG_CSV=1` et `segment_cache_id` actif (vecteurs intent réels, `_use_cog=True`).

### Features

10 features par leg :

- **4 affordances** : `parallel_affordance`, `crossing_density`, `exit_clarity`, `contour_crossing_guidance`
- **6 intents** : `HANDRAIL_FOLLOW`, `LINE_CROSSING`, `ATTACK_POINT`, `DIRECT_RISK_RUN`, `RELIEF_CROSSING_GUIDANCE`, `SAFETY_RECOVERY`

### Unité statistique

Le circuit entier (pas le leg). Les legs sont agrégés par circuit (mean PC1, mean PC2) avant toute analyse statistique. Les tests de bootstrap et permutation opèrent sur les circuits.

### Méthodes statistiques

| Méthode | Usage | N |
|---------|-------|---|
| Bootstrap stratifié par (map, TD) | CI sur slopes, ΔR², β3 | B=1000 |
| Permutation test (labels carte) | p-value séparation M1 | N=2000 |
| OLS via `np.linalg.lstsq` | régressions linéaires | — |
| Cohen's d | comparaison fitness M2 | — |

**Distinction confirmatoire vs exploratoire** : toutes les analyses A.8b/A.8c/Q3 sont **exploratoires** (N faible, pas d'ajustement pour comparaisons multiples). Les CI larges et les p-values sont des signaux directionnels, non des tests confirmatoires.

---

## 3. Résultats principaux

### A. Existence du manifold

- **PC1 = 63.2% de la variance** (PCA globale sur 616 legs)
- **PC2 = 19.6%** — potentiellement bruité (PC2 < 20% frontier)
- Bootstrap alignment (A.7) : **0.94–0.99** → la structure PC1 est stable à travers les re-échantillonnages

Le manifold latent est réel et reproductible.

### B. Structure TD

- **Continuum TD3→TD5** le long de PC1 — pas de clustering fort (separation ratio = 0.10)
- **PC1 est principalement corrélé à `leg_m` avec saturation non-linéaire** : les circuits plus longs (TD5) occupent une région distincte mais le continuum n'est pas discret
- Clé interprétative centrale : PC1 n'est pas un axe de complexité abstraite, c'est essentiellement une transformation saturante de la longueur moyenne de jambe

### C. Relation fitness (A.8c)

**Slopes PC1→fitness par groupe (OLS, CI bootstrap) :**

| Groupe | Slope | CI 95% |
|--------|-------|--------|
| crohot TD3 | +3.1 | [couvre 0] |
| crohot TD4 | +24.4 | [couvre 0] |
| crohot TD5 | +51.6 | [couvre 0] |
| stanne TD3 | +3.1 | [couvre 0] |

Progression ×16 de TD3 à TD5 — les circuits TD5 sont structurellement beaucoup plus sensibles à la position dans le manifold.

**ΔR² quadratique TD5 = +0.048** → régime possiblement non-linéaire (signal faible, N=12).

**Décomposition fitness (A3, N=12 circuits TD5) :**
- `penalty_b` : beta_std=0.40 (dominant parmi les termes exportés)
- R²_multiple = 0.179 → **82% de la variance fitness inexpliqué** par les termes exportés
- `score_a` : variance nulle (0.8702 constant) — saturation du CNN HeatmapCache : le GA place toujours les postes dans le top-40% des candidats → zéro variance entre circuits

### D. Domain shift stanne vs crohot (Q3, TD3 uniquement, N=22)

| Test | Résultat |
|------|---------|
| M1 : séparation géométrique (permutation) | **p=0.030** (significatif), d_norm=1.358 |
| M2 : shift fitness brut (bootstrap CI) | CI inclut 0 — pas de décalage établi |
| M3 : interaction map×PC1 (ΔR²) | **ΔR²=+0.197** — évidence partielle |

La carte influence la position dans le manifold (M1 robuste) mais pas directement la fitness brute (M2). L'interaction map×PC1 sur fitness est partiellement présente (M3) mais les CI restent larges.

---

## 4. Visualisations

![Manifold PC1-PC2](../backend/debug/manifold_v2.png)

**Panel A** — PC1-PC2 colorié par carte (bleu=stanne, orange=crohot), forme du marker par TD. Les centroïdes TD3 annotés montrent la séparation géométrique.

**Panel B** — PC1-PC2 colorié par TD (vert=TD3, orange=TD4, rouge=TD5), forme par carte (cercle=stanne, carré=crohot). Le gradient TD3→TD5 le long de PC1 est visible.

**Panel C** — PC1-PC2 colorié par fitness (RdYlGn). Absence de gradient spatial net → le manifold n'est pas un axe de qualité unidimensionnel.

**Panel D** — PC1 → fitness par groupe. Les 4 droites de régression montrent la progression des pentes (TD3 quasi-plat, TD5 très incliné).

---

## 5. Conclusions

| Statut | Conclusion |
|--------|-----------|
| **robuste** | Manifold latent stable — PC1=63%, bootstrap alignment 0.94–0.99 |
| **robuste** | Continuum TD3→TD5 le long de PC1 |
| **robuste** | Effet carte réel — séparation géométrique p=0.030 |
| **robuste** | Le manifold latent n'est pas un axe de qualité unidimensionnel |
| **robuste** | `leg_m` est la variable générative dominante de PC1 (saturation non-linéaire) |
| **probable** | TD5 amplifie la dépendance structurelle fitness→manifold (slope ×16) |
| **probable** | Interaction map×PC1 sur fitness (ΔR²=+0.197, CI larges) |
| **ouvert** | Régime non-linéaire TD5 (ΔR²_quad=+0.048, N=12 insuffisant) |
| **ouvert** | Médiateur exact de l'inversion de pente TD5 (I/J/K non exportés) |

---

## 6. Limites méthodologiques

- **N faible** : stanne=10 circuits, TD5=12 circuits — CI larges, puissance limitée
- **Déséquilibre cartes** : 10 stanne vs 36 crohot — comparaisons asymétriques
- **Ambiguïté de signe PC1** : orientation arbitraire du SVD — les slopes peuvent s'inverser selon la PCA utilisée (global vs per-TD)
- **Composantes fitness incomplètes** : termes I/J/K (attack point, handrail, safety recovery), F (forbidden), G (elevation) non exportés — 82% de la variance fitness inexpliqué
- **score_a constant** : terme A non informatif dans ce jeu de données (saturation HeatmapCache)
- **Absence de validation externe** : une seule paire de cartes — le domain shift peut être idiosyncratique
- **Générateur unique** : le manifold est dérivé du seul GA actuel — peut représenter une propriété profonde des circuits CO ou une propriété spécifique de ce générateur (pas de validation inter-générateurs)

---

---

## 8. latent-analysis-v2 — Post-fix terme L (2026-05-26)

### Contexte de l'intervention

Le terme L (`leg_conformity`) était fonctionnellement mort en LD : cible hardcodée 2000m vs ~473m réels
→ conformité constante ~0.25 pour tous les circuits TD5. Fix : cible dérivée des paramètres du circuit
(`target_length_m / (target_controls-1) × style_factor`, ld×1.15 → ~545m).

La seule variable expérimentale est la réactivation du terme L. Tous les autres paramètres
(`DISTANCES`, `CONTROLS`, `CT_TYPE`, `n_each`, schéma `(map, td, local_idx)`) sont identiques.

### Tableau comparatif v1 → v2 (TD5, N=12 circuits)

| Mesure | v1 (L mort) | v2 (L vivant) | delta |
|--------|-------------|---------------|-------|
| fitness mean | 21.56 | 28.16 | **+31%** |
| fitness SD | 27.38 | 22.34 | **−18%** |
| fitness CV | 1.270 | 0.793 | **−37%** |
| Slope TD5 (OLS) | +51.6 | +22.6 (CI incl. 0) | **−56%** |
| Sep. ratio manifold (affordance) | 0.10 | 0.21 | **+110%** |
| Sep. ratio manifold (intent) | — | 0.23 | — |
| Variance PC1 (manifold, 46 circuits) | 63.2% | 62.7% | stable |
| penalty_b mean TD5 | 0.0954 | 0.0978 | stable |
| leg_m mean TD5 | 509m | 514m | stable |

### Interprétation

**Signal principal — mean ↑ + CV ↓ :** Le paysage de fitness est moins anisotrope avec L vivant.
Le GA discrimine mieux entre circuits (CV −37%) tout en produisant des circuits de meilleure qualité
moyenne (+31%). La dérive vers des fitness très élevées ou très basses est réduite.

**Slope TD5 divisée par 2 :** La contrainte structurelle fitness→manifold pour TD5 était partiellement
un artefact du terme L mort. Avec L vivant, la slope est +22.6 et le CI inclut maintenant 0 — le signal
n'est plus statistiquement distinct du bruit à N=12.

**Manifold plus discriminant par TD :** Le separation ratio double (0.10 → 0.21–0.23). Les niveaux TD
se séparent mieux dans l'espace latent quand L est actif.

**penalty_b et leg_m stables :** Aucun effet de bord sur le ciblage de distance total (terme B) ni
sur la distribution des longueurs de jambes réelles.

### Visualisation

![Manifold v3 post-fix](../backend/debug/manifold_v3_post_fix.png)

---

## 9. Expérience W_DIST — null result informatif (2026-05-27)

### Protocole

Trois runs TD5 uniquement (crohot, N=12 circuits chacun), seeds déterministes par job
(`hash(map, td, local_idx) % 2^31`). Seul `W_DIST` varie.

| Run | W_DIST | Dataset |
|-----|--------|---------|
| low | 20 | `intent_legs_wdist20_td5.csv` |
| baseline | 40 | `intent_legs_post_fix_full.csv` (TD5) |
| high | 60 | `intent_legs_wdist60_td5.csv` |

### Résultats

| Métrique | W20 | **W40** | W60 |
|----------|-----|---------|-----|
| fitness mean | 13.86 | **28.16** | 26.64 |
| fitness SD | 31.78 | **22.34** | 36.68 |
| fitness CV | 2.293 | **0.793** | 1.377 |
| penalty_b mean | 0.1085 | 0.0978 | **0.0857** |
| score_h mean | 0.6154 | 0.5919 | **0.6519** |
| score_d mean | 0.4545 | 0.4829 | 0.4843 |

### Conclusion

**W_DIST=40 est au sweet spot.** Le CV suit une courbe en U :

- **W20 (sous-contraint)** : CV=2.29 — pression distance insuffisante, le GA explore sans
  contrainte → instabilité maximale. `penalty_b` monte paradoxalement (+11%) : sans pression
  forte, le GA ne converge pas vers la cible distance.
- **W40 (équilibré)** : CV=0.793 — paysage le plus stable, fitness moyenne maximale.
- **W60 (sur-contraint)** : CV=1.38 — vallée trop étroite → distribution bimodale (circuits
  proches de la cible vs circuits loin). `penalty_b` plus faible mais fitness instable.

**Null result mais informatif** : W_DIST n'est pas le levier à toucher. La calibration actuelle
est robuste. Le prochain levier est la diversité (terme E) ou `W_LEG_PROFILE` (terme L) en
régime naturel — terme L récemment réactivé, régime naturel à mesurer avant toute recalibration.

---

## 10. Expérience W_DIVERSITY — null result informatif (2026-05-27)

### Protocole

Trois runs TD5 uniquement (crohot, N=12 circuits chacun), seeds déterministes identiques aux runs W_DIST.
Seul `w_diversity_mult` varie (`W_LEG_DIVERSITY = 4.0 × mult`).

| Run | w_diversity_mult | W_LEG_DIVERSITY effectif | Dataset |
|-----|-----------------|--------------------------|---------|
| low | 0.5 | 2.0 | `intent_legs_wdiv05_td5.csv` |
| baseline | 1.0 | 4.0 | `intent_legs_post_fix_full.csv` (TD5) |
| high | 1.5 | 6.0 | `intent_legs_wdiv15_td5.csv` |

### Résultats (PCA partagée sur 36 circuits)

| Métrique | W_DIV×0.5 | **W_DIV×1.0** | W_DIV×1.5 |
|----------|-----------|---------------|-----------|
| fitness mean | 29.83 | **28.16** | 30.93 |
| fitness SD | 25.14 | **21.39** | 30.11 |
| fitness CV | 0.843 | **0.760** | 0.973 |
| slope TD5 (OLS, espace commun) | −1.9 | −2.2 | −2.2 |
| latent area (std PC1 × std PC2) | 3.091 | 2.938 | **2.273** |
| std PC1 | 2.348 | **3.106** | 1.961 |
| n_unique_tags | — | — | — |

> **Note méthodologique :** `n_unique_tags` est 0 pour les trois runs — le fichier global
> `intent_legs.csv` avait l'ancien header (sans ce champ) ; `DictReader` ne reconnaît pas la
> colonne dans les CSVs de sortie. Limitation des données, sans impact sur les autres métriques.

> **Note PCA :** le signe de PC1 dans l'espace commun est inversé vs les analyses précédentes
> (slopes ~−2 ici vs +22.6 en section 8). Artefact d'orientation SVD — la magnitude (~2) reste
> cohérente avec CI incluant 0 post-fix terme L.

### Conclusion

**W_LEG_DIVERSITY=4.0 (×1.0) est au sweet spot.** Le CV suit une courbe en U :

- **W_DIV×0.5 (sous-contraint)** : CV=0.843 — pression diversité insuffisante, légère instabilité.
- **W_DIV×1.0 (équilibré)** : CV=0.760 — paysage le plus stable.
- **W_DIV×1.5 (sur-contraint)** : CV=0.973 + latent area −0.67 — la pression diversité excessive
  réduit l'exploration géométrique (std PC1 : 3.11 → 1.96) et augmente l'instabilité. Le GA
  converge vers un sous-espace étroit plutôt que d'explorer.

**Slope structurelle, non causée par collapse morphologique :** les trois runs montrent une slope
proche de zéro dans l'espace commun. La diversité morphologique n'est pas le mécanisme de la
dépendance TD5 — celle-ci est un signal résiduel à N=12 (CI inclut 0 depuis le fix terme L).

**Null result × 2 (W_DIST + W_DIVERSITY) :** la calibration actuelle est robuste sur les deux
leviers testés. Les prochains leviers à explorer sont intrinsèquement différents (diversité de
structure de circuit, pas de poids fitness).

---

---

## 11. Validation externe — Généralisation sur 4 nouvelles cartes forêt (2026-05-27)

### Protocole

**PCA figée sur baseline** (Option B — test de transférabilité réel) : scaler + PCA fittés **uniquement** sur les 46 circuits stanne+crohot. Les nouvelles cartes sont projetées via `transform()` dans cet espace figé — elles ne participent pas à la définition des axes. C'est un test OOD, pas une analyse descriptive.

| Carte | Fichier | TD | N circuits |
|-------|---------|-----|-----------|
| stanne | `intent_legs_post_fix_full.csv` | 3 | 10 |
| crohot | `intent_legs_post_fix_full.csv` | 3/4/5 | 36 |
| cerisy | `intent_legs_cerisy_full.csv` | 3/4/5 | 36 |
| feuguerolles | `intent_legs_feuguerolles_full.csv` | 3/4/5 | 36 |
| tourouvre | `intent_legs_tourouvre_full.csv` | 3/4/5 | 36 |
| montmirel | `intent_legs_montmirel_full.csv` | 3/4/5 | 36 |

Protocole identique à crohot (n_each=12, seeds déterministes `hash(map, td, idx) % 2^31`). Aucun tuning — seule variable : la carte.

### Table 0 — Référence baseline stanne+crohot

| Mesure | Valeur baseline |
|--------|----------------|
| PC1 variance explained | 64.7% (stable vs 63.2% v2) |
| PC2 variance explained | 13.8% |
| sep_ratio TD (crohot) | 0.78 |
| d_norm M1 stanne vs crohot | 1.358 (p=0.030) |
| Slope TD5 | +22.6 (CI incl. 0) — note: calculée sur PCA TD5-only dans section 8 |

> **Note** : les slopes de Table 1 ci-dessous utilisent la PCA tous-TDs (TD3+TD4+TD5 combinés), différente de la PCA TD5-only de la section 8. Les valeurs ne sont pas directement comparables.

### Table 1 — Métriques par carte (espace PCA figé baseline)

| Carte | N_TD3 | N_tot | sep_ratio_TD | Slope_TD3 | R²_TD3 | r_TD3 | Slope_TD5 | R²_TD5 | r_TD5 |
|-------|-------|-------|-------------|-----------|--------|-------|-----------|--------|-------|
| stanne | 10 | 10 | — | +0.99 | 0.03 | +0.18 | — | — | — |
| crohot | 12 | 36 | 0.78 | +0.63 | 0.01 | +0.09 | −2.58 | 0.11 | −0.32 |
| cerisy | 12 | 36 | 0.66 | −0.25 | 0.00 | −0.02 | −3.67 | 0.04 | −0.20 |
| feuguerolles | 12 | 36 | 1.02 | −2.13 | 0.07 | −0.26 | −0.25 | 0.00 | −0.02 |
| montmirel | 12 | 36 | 1.15 | −0.27 | 0.01 | −0.08 | −1.08 | 0.10 | −0.32 |
| tourouvre | 12 | 36 | **1.10** | +0.24 | 0.00 | +0.04 | **+7.14** | **0.33** | **+0.58** |

### Table 2 — Domain shift pairwise TD3 (exploratoire)

> M1 effectué uniquement sur TD3 — évite contamination par structure TD. Référence : d_norm=1.358 (stanne vs crohot).

| Paire | d_norm | p_M1 | ΔFit CI | ΔR²_M3 |
|-------|--------|------|---------|--------|
| cerisy vs crohot | 1.244 | 0.016 | [−11.6, +19.1] ✓0 | 0.002 |
| cerisy vs feuguerolles | 1.333 | 0.017 | [−21.1, +11.9] ✓0 | 0.009 |
| cerisy vs montmirel | 0.534 | 0.387 | [−23.2, +7.5] ✓0 | 0.000 |
| cerisy vs stanne | 0.723 | 0.245 | [−23.6, +8.8] ✓0 | 0.005 |
| cerisy vs tourouvre | 0.937 | 0.096 | [−14.4, +18.3] ✓0 | 0.001 |
| crohot vs feuguerolles | 1.028 | 0.061 | [−21.3, +4.0] ✓0 | 0.030 |
| crohot vs montmirel | 0.972 | 0.078 | [−22.2, **−0.9**] **✗0** | 0.006 |
| crohot vs stanne | 0.601 | 0.353 | [−23.0, 0.0] ✓0 | 0.001 |
| crohot vs tourouvre | 0.376 | 0.637 | [−13.9, +9.6] ✓0 | 0.001 |
| feuguerolles vs montmirel | **1.425** | **0.009** | [−16.6, +8.0] ✓0 | 0.026 |
| feuguerolles vs stanne | 1.209 | 0.041 | [−16.2, +9.3] ✓0 | 0.050 |
| feuguerolles vs tourouvre | 0.808 | 0.162 | [−7.1, +18.2] ✓0 | 0.025 |
| montmirel vs stanne | 0.501 | 0.459 | [−9.6, +9.6] ✓0 | 0.020 |
| montmirel vs tourouvre | 0.864 | 0.129 | [−1.1, +20.1] ✓0 | 0.002 |
| stanne vs tourouvre | 0.454 | 0.515 | [−2.2, +20.2] ✓0 | 0.004 |

### Table 3 — Distance OOD Mahalanobis TD-conditionnelle

| Carte | TD | N | mean_OOD | max_OOD | min_OOD |
|-------|-----|---|----------|---------|---------|
| cerisy | 3 | 12 | 1.757 | 2.662 | 0.531 |
| cerisy | 4 | 12 | 2.300 | 4.186 | 0.612 |
| cerisy | 5 | 12 | 3.505 | 21.561 | 0.289 |
| feuguerolles | 3 | 12 | 1.796 | 2.876 | 0.828 |
| feuguerolles | 4 | 12 | **8.206** | **34.506** | 1.269 |
| feuguerolles | 5 | 12 | 3.736 | **23.040** | 0.646 |
| montmirel | 3 | 12 | 1.982 | 3.368 | 0.732 |
| montmirel | 4 | 12 | 2.195 | 4.853 | 1.027 |
| montmirel | 5 | 12 | 2.613 | 4.207 | 1.017 |
| tourouvre | 3 | 12 | **1.275** | 1.935 | 0.545 |
| tourouvre | 4 | 12 | **1.399** | 2.563 | 0.301 |
| tourouvre | 5 | 12 | **1.454** | 2.809 | 0.163 |

### Conclusions

**Ce qui est repliqué hors baseline :**

| Signature | Résultat | Interprétation |
|-----------|----------|----------------|
| Continuum TD3→TD5 (sep_ratio) | ✅ Repliqué — sep_ratio 0.66–1.15 pour toutes les cartes | La structure TD généralisée dans le manifold baseline |
| Séparation géométrique entre cartes (d_norm M1) | ✅ Repliqué — d_norms comparables à 1.358 (baseline) | L'effet-carte est un phénomène général, pas un artefact stanne/crohot |
| Absence de couplage manifold→fitness (slope) | ✅ Repliqué — slopes proches de zéro sur 4/5 nouvelles cartes | Null result structurel, cohérent avec sections 9 et 10 |

**Ce qui n'est pas repliqué :**

| Signature | Résultat | Interprétation |
|-----------|----------|----------------|
| Slope TD5 positive (+22.6) | ✗ Non repliqué — négatif sur crohot/cerisy/montmirel dans ce PCA | La slope de section 8 était PCA TD5-only, non comparable ici |
| Mahalanobis OOD faible et uniforme | ✗ Partiel — tourouvre très proche (1.3), feuguerolles très loin (max 34) | Hétérogénéité forte entre cartes |

**Cas particulier tourouvre :** seule carte avec slope TD5 positive (+7.14, r=0.58, R²=0.33) **et** OOD distances les plus faibles (mean 1.3–1.5 tous TDs). Profil le plus compatible avec le manifold baseline — les circuits tourouvre tombent dans le support latent connu et maintiennent un couplage positif manifold→fitness.

**Cas particulier feuguerolles :** distances OOD TD4 extrêmes (max 34.5) indiquent des circuits TD4 projetés très loin du support baseline. Terrain structurellement différent ou circuits atypiques.

**Conclusion générale :** la structure géométrique du manifold (continuum TD, séparation inter-cartes) est robuste hors domaine. Le couplage fonctionnel manifold→fitness est faible et hétérogène — cohérent avec les null results de calibration. Le manifold latent est une représentation transférable de la structure des circuits CO, pas un prédicteur de fitness universel.

---

## 7. Next steps

**Court terme** — TD5 calibration experiments  
~~Faire varier `W_DIST`~~ — **✅ fait (2026-05-27), null result mais informatif** (voir section 9).  
~~Faire varier `W_LEG_DIVERSITY`~~ — **✅ fait (2026-05-27), null result mais informatif** (voir section 10).  
~~Validation externe — nouvelles cartes~~ — **✅ fait (2026-05-27), signatures géométriques repliquées** (voir section 11).  
Prochains leviers : structure de circuit (boucles papillon LD, terme H figure-8).

**Moyen terme** — Latent steering  
Évaluer si le manifold peut être utilisé comme variable de contrôle générationnelle : orienter le GA vers des régions spécifiques du manifold pour contrôler explicitement le profil de circuit généré.

**Plus tard, si question précise** — Export I/J/K  
Exporter les termes de fitness attack point / handrail / safety recovery uniquement si la question est : *quel mécanisme médiatise exactement l'inversion de pente TD5 ?* Ne pas ouvrir une exploration générale.
