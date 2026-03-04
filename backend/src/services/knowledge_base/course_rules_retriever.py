"""
Étape 11b — Récupération des règles de tracé pertinentes depuis LocalRAG.

Fournit get_course_rules() pour injection dans le prompt LLM de l'AIGenerator.
"""

from __future__ import annotations

_MAX_CHARS_PER_CHUNK = 350  # Tronquer les chunks pour garder un prompt raisonnable


def get_course_rules(
    circuit_type: str,
    td_level: int,
    n: int = 4,
) -> str:
    """
    Retourne les règles de tracé IOF/FFCO pertinentes, formatées pour injection dans un prompt LLM.

    Args:
        circuit_type: "sprint", "forest", "md", "couleur"
        td_level: 1–5
        n: nombre de chunks à récupérer

    Returns:
        Texte formaté ou chaîne vide si LocalRAG indisponible ou vide.
    """
    try:
        from .local_rag import LocalRAG
        rag = LocalRAG()
        if not rag.qr_list or rag.embeddings is None:
            return ""

        query = (
            f"règles placement balise poste {circuit_type} niveau TD{td_level} "
            f"distance longueur jambe angle dog-leg choix itinéraire IOF FFCO"
        )
        chunks = rag.search_chunks(query, n=n, circuit_type=circuit_type, min_score=0.18)

        if not chunks:
            # Fallback sans filtre circuit_type
            chunks = rag.search_chunks(query, n=n, min_score=0.18)

        if not chunks:
            return ""

        lines = [f"### Règles de tracé IOF/FFCO (circuit {circuit_type}, TD{td_level}) :"]
        for c in chunks:
            text = c["text"][:_MAX_CHARS_PER_CHUNK].replace("\n", " ").strip()
            lines.append(f"- [{c['source']}] {text}")

        return "\n".join(lines)

    except Exception as e:
        print(f"[course_rules_retriever] Erreur : {e}")
        return ""


def get_placement_rules(circuit_type: str, td_level: int) -> dict:
    """
    Retourne les seuils numériques calibrés IOF/FFCO depuis placement_rules.json.

    Args:
        circuit_type: "sprint", "forest", "md", "couleur"
        td_level: 1–5

    Returns:
        Dict avec min_leg_m, max_leg_m, dog_leg_angle_deg, max_climb_ratio, etc.
    """
    import json
    from pathlib import Path

    _RULES_PATH = Path(__file__).parent / "placement_rules.json"
    try:
        rules_data = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return rules_data.get("_defaults", {})

    td_key = f"TD{td_level}"
    category = rules_data.get(circuit_type, rules_data.get("forest", {}))
    result = category.get(td_key, None)

    if result is None:
        # Fallback : TD le plus proche
        for fallback_td in [td_level + 1, td_level - 1, 3]:
            result = category.get(f"TD{fallback_td}", None)
            if result:
                break

    if result is None:
        result = rules_data.get("_defaults", {})

    return result
