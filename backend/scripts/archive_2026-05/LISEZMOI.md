# Scripts archivés — mai 2026

Ces scripts mesuraient les propriétés latentes du moteur v1 (LRI, PCA, diversité).

Leurs conclusions sont classées **non établies** (constat C2, `docs/plan/REGISTRE.md`) :
l'hypothèse implicite était que `evaluate_fitness` (termes A→L) pilotait la génération.
Or la sélection réelle est faite par `_default_scoring`  — `evaluate_fitness` n'est
appelée qu'en télémétrie depuis le premier commit. Les mesures portaient donc sur une
fonction jamais branchée sur la sélection.
