"""Module RAG Local basé sur SentenceTransformers et Ollama."""

import json
import os
import subprocess
from sentence_transformers import SentenceTransformer
import numpy as np

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

OLLAMA_URL = "http://localhost:11434"

SEUIL_EXACT = 0.65  # Au-dessus -> réponse directe du dataset
SEUIL_OLLAMA = 0.35  # Entre SEUIL_OLLAMA et SEUIL_EXACT -> Ollama avec contexte
TOP_K = 3  # Nombre de Q/R à passer en contexte à Ollama


def charger_dataset():
    """Charge le dataset Q/R principal + les chunks PDF ingérés (Étape 11a)."""
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    )
    qr = []

    # Dataset Q/R principal (ffco-iof-v7)
    chemin_qr = os.path.join(base_dir, "Lora", "mondial_tracage_QR_v4.jsonl")
    if os.path.exists(chemin_qr):
        with open(chemin_qr, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    qr.append(json.loads(line))
    else:
        print(f"[WARNING] Dataset QR not found: {chemin_qr}")

    # Chunks PDF ingérés (Étape 11a) — data/pdf_knowledge.jsonl
    chemin_pdf = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "data", "pdf_knowledge.jsonl"
    )
    chemin_pdf = os.path.normpath(chemin_pdf)
    if os.path.exists(chemin_pdf):
        count_before = len(qr)
        with open(chemin_pdf, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    qr.append(json.loads(line))
        print(f"[OK] {len(qr) - count_before} chunks PDF chargés depuis {chemin_pdf}")
    else:
        print(f"[INFO] Pas de chunks PDF. Lancez POST /api/v1/knowledge/ingest-docs pour indexer les PDF.")

    return qr


def trouver_meilleures_reponses(question, qr_list, model, embeddings, top_k=TOP_K):
    q_embed = model.encode([question], normalize_embeddings=True)
    scores = np.dot(embeddings, q_embed.T).flatten()
    scores = np.clip(scores, -1.0, 1.0)
    top_indices = np.argsort(scores)[::-1][:top_k]
    resultats = [(qr_list[i], float(scores[i])) for i in top_indices]
    return resultats


_SYSTEM_PROMPT_CO = """Tu es AItraceur, assistant expert en course d'orientation (CO) selon les règles IOF/FFCO.

**Niveaux techniques TD (Technical Difficulty) :**
| Niveau | Terrain | Public cible | Postes placés sur |
|--------|---------|--------------|-------------------|
| TD1 | Chemin tout le parcours | Débutants | Carrefours, routes, objets évidents |
| TD2 | Sentiers visibles, peu de hors-chemin | Initiés | Croisements clairs, lisières évidentes |
| TD3 | Hors-chemin possible, formes de terrain | Habitués | Dépressions, buttes, éperons |
| TD4 | Hors-chemin courant, détails fins | Experts | Rochers isolés, petites dépressions |
| TD5 | Terrain complexe, forêt dense | Élite | Détails très fins, microrelief |

**Niveaux physiques PD (D+ par km) :**
| Niveau | D+/km | Catégories typiques |
|--------|-------|---------------------|
| PD1 | 0–10 m/km | Blanc, Jaune, Sprint |
| PD2 | 10–20 m/km | Orange, Vert, Violet |
| PD3 | 20–30 m/km | Bleu, Rouge |
| PD4 | 30–40 m/km | H/D40+ |
| PD5 | >40 m/km | H21E, D21E élite |

**Règles IOF clés :**
- Distance minimale entre postes : 60 m (IOF AA3.5.5)
- Dog-leg interdit : le poste ne doit pas révéler le suivant (IOF AA16.8)
- Départ → 1er poste : ≥ 100 m (AA3.4)
- Temps de victoire : Sprint 12–15 min, Court 25–35 min, Long 40–60 min (H/D21E)

**Exemples de réponses correctes :**
Q: Qu'est-ce que TD3 ?
R: TD3 = niveau technique moyen. Postes sur formes de terrain (dépressions, buttes, éperons). Hors-chemin autorisé. Catégories : H/D35, Rouge, Bleu.

Q: Quelle est la distance minimale entre deux postes ?
R: 60 mètres (IOF AA3.5.5). En dessous, les postes sont trop proches et pénalisent le score.

Q: Qu'est-ce qu'un dog-leg ?
R: Faute de traçage : le chemin logique vers un poste passe trop près du poste suivant, le révélant. Interdit par IOF AA16.8.

Réponds toujours en français, de façon courte et précise (2–4 phrases max)."""


def demander_ollama(question, contextes):
    """Interroge ffco-iof-v7 via l'API REST Ollama (system prompt CO/IOF injecté)."""
    # Construire le message utilisateur
    if contextes:
        ctx_text = "\n\n".join(
            f"Q: {c['instruction']}\nR: {c['output']}" for c in contextes
        )
        user_content = f"Contexte RAG :\n{ctx_text}\n\nQuestion : {question}"
    else:
        user_content = question

    # Essayer l'API REST Ollama (prioritaire)
    if _REQUESTS_AVAILABLE:
        try:
            resp = _requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": "ffco-iof-v7",
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 250},
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT_CO},
                        {"role": "user", "content": user_content},
                    ],
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "").strip() or None
        except Exception as e:
            print(f"[WARNING] Ollama API REST indisponible : {e}")
            # Fall through to subprocess fallback

    # Fallback subprocess (sans system prompt — moins bon mais fonctionnel)
    try:
        result = subprocess.run(
            ["ollama", "run", "ffco-iof-v7", user_content],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        if result.returncode != 0:
            print(f"[WARNING] Ollama subprocess non-zero ({result.returncode}): {result.stderr.strip()}")
            return None
        return result.stdout.strip() or None
    except FileNotFoundError:
        print("[WARNING] Ollama non installe ou non trouve dans le PATH.")
        return None
    except subprocess.TimeoutExpired:
        print("[WARNING] Ollama timeout apres 60s.")
        return None
    except Exception as e:
        print(f"[WARNING] Erreur Ollama inattendue : {e}")
        return None


class LocalRAG:
    """Classe pour encapsuler la logique RAG locale (Singleton)"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LocalRAG, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        print("[INFO] Initialisation du RAG local...")
        try:
            self.model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
            self.qr_list = charger_dataset()

            if self.qr_list:
                textes_a_indexer = [
                    f"{item['instruction']} {item['output']}" for item in self.qr_list
                ]
                self.embeddings = self.model.encode(
                    textes_a_indexer, normalize_embeddings=True
                )
                print(f"[OK] {len(self.qr_list)} Q/R indexees - RAG local pret !")
            else:
                self.embeddings = None
                print("[WARNING] Dataset RAG vide ou non trouve.")
            self._initialized = True
        except Exception as e:
            print(f"[ERROR] Erreur initialisation RAG local: {e}")
            self._initialized = False
            self.qr_list = []
            self.embeddings = None

    def query(self, question: str):
        FALLBACK = "Ollama non disponible. Assurez-vous qu'Ollama est lance et que le modele ffco-iof-v7 est installe."

        if not self.qr_list or self.embeddings is None:
            reponse = demander_ollama(question, [])
            return reponse or FALLBACK, []

        resultats = trouver_meilleures_reponses(
            question, self.qr_list, self.model, self.embeddings
        )
        meilleure, score = resultats[0]

        if score >= SEUIL_EXACT:
            return meilleure["output"], [
                {"source": "Dataset", "score": score, "type": "exact_match"}
            ]
        elif score >= SEUIL_OLLAMA:
            contextes = [r[0] for r in resultats]
            sources = [
                {"source": "Dataset RAG", "score": r[1], "match": r[0]["instruction"]}
                for r in resultats
            ]
            reponse = demander_ollama(question, contextes)
            return reponse or FALLBACK, sources
        else:
            reponse = demander_ollama(question, [])
            return reponse or FALLBACK, []

    def search_chunks(
        self,
        query: str,
        n: int = 5,
        circuit_type: str = None,
        min_score: float = 0.20,
    ) -> list:
        """
        Recherche sémantique directe dans le dataset (sans passer par Ollama).
        Retourne les n meilleurs chunks correspondants.

        Chaque résultat : {"text": str, "source": str, "score": float, "circuit_type": str}
        """
        if not self.qr_list or self.embeddings is None:
            return []

        resultats = trouver_meilleures_reponses(
            query, self.qr_list, self.model, self.embeddings, top_k=max(n * 3, 15)
        )

        chunks = []
        for item, score in resultats:
            if score < min_score:
                continue
            item_ct = item.get("circuit_type", "all")
            # Filtre par circuit_type si spécifié ("all" passe toujours)
            if circuit_type and item_ct not in ("all", circuit_type):
                continue
            chunks.append({
                "text": item.get("output", item.get("instruction", "")),
                "source": item.get("source", "Dataset"),
                "score": round(score, 3),
                "circuit_type": item_ct,
            })
            if len(chunks) >= n:
                break

        return chunks

    def reload(self):
        """Recharge le dataset (après ingestion de nouveaux PDF)."""
        self._initialized = False
        self.qr_list = []
        self.embeddings = None
        self.__init__()
