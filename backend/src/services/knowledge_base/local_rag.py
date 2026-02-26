"""Module RAG Local basé sur SentenceTransformers et Ollama."""

import json
import os
import subprocess
from sentence_transformers import SentenceTransformer
import numpy as np

SEUIL_EXACT = 0.65  # Au-dessus -> réponse directe du dataset
SEUIL_OLLAMA = 0.35  # Entre SEUIL_OLLAMA et SEUIL_EXACT -> Ollama avec contexte
TOP_K = 3  # Nombre de Q/R à passer en contexte à Ollama


def charger_dataset():
    # Trouver le bon chemin vers le jsonl (dans Lora/)
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    )
    chemin = os.path.join(base_dir, "Lora", "mondial_tracage_QR_v4.jsonl")

    qr = []
    if not os.path.exists(chemin):
        print(f"[WARNING] Dataset not found at {chemin}")
        return qr

    with open(chemin, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            qr.append(json.loads(line))
    return qr


def trouver_meilleures_reponses(question, qr_list, model, embeddings, top_k=TOP_K):
    q_embed = model.encode([question], normalize_embeddings=True)
    scores = np.dot(embeddings, q_embed.T).flatten()
    scores = np.clip(scores, -1.0, 1.0)
    top_indices = np.argsort(scores)[::-1][:top_k]
    resultats = [(qr_list[i], float(scores[i])) for i in top_indices]
    return resultats


def demander_ollama(question, contextes):
    if contextes:
        ctx_text = "\n\n".join(
            f"Q: {c['instruction']}\nR: {c['output']}" for c in contextes
        )
        prompt = f"""Tu es AItraceur, expert CO FFCO/IOF.
Utilise le contexte suivant pour t'aider à répondre :

CONTEXTE :
{ctx_text}

QUESTION : {question}

Réponds en français, de façon courte et précise."""
    else:
        prompt = f"""Tu es AItraceur, expert CO FFCO/IOF.

QUESTION : {question}

Réponds en français, de façon courte et précise. Si tu ne sais pas, dis-le."""

    # Utiliser le modèle fine-tuné Lora
    result = subprocess.run(
        ["ollama", "run", "ffco-iof-v7", prompt],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


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
        if not self.qr_list or self.embeddings is None:
            return demander_ollama(question, []), []

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
            return reponse, sources
        else:
            reponse = demander_ollama(question, [])
            return reponse, []
