"""
Étape 11a — Ingestion des PDF docs IOF/FFCO vers LocalRAG.

Usage:
    python -m src.services.knowledge_base.ingest_docs          # depuis backend/
    ou via endpoint POST /api/v1/knowledge/ingest-docs
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import List, Dict

try:
    import fitz  # pymupdf
    _FITZ_AVAILABLE = True
except ImportError:
    _FITZ_AVAILABLE = False

# Répertoires PDF
_BACKEND_ROOT = Path(__file__).parents[4]  # e:\Vikazim\AItraceur
DOCS_DIRS = [
    _BACKEND_ROOT / "docs",
    _BACKEND_ROOT / "docs controleur",
]

# Fichier de sortie (JSONL, chargé par LocalRAG au démarrage)
OUTPUT_JSONL = Path(__file__).parents[3] / "data" / "pdf_knowledge.jsonl"

# Métadonnées par mot-clé dans le nom de fichier
_META_MAP = [
    ("Sprint_Course_Planning", {"circuit_type": "sprint", "category": "IOF", "td_min": 3}),
    ("Forest_Course_Planning", {"circuit_type": "forest", "category": "IOF", "td_min": 2}),
    ("complex_urban", {"circuit_type": "sprint", "category": "IOF", "td_min": 4}),
    ("Course-planning-guidelines-Sprint", {"circuit_type": "sprint", "category": "IOF", "td_min": 3}),
    ("Guidelines-for-Course-Planning_Sprint", {"circuit_type": "sprint", "category": "IOF", "td_min": 3}),
    ("Appendix-A-Course-Planning", {"circuit_type": "all", "category": "IOF", "td_min": 1}),
    ("TRACAGE PRINCIPES", {"circuit_type": "all", "category": "FFCO", "td_min": 1}),
    ("TRACAGE ASPECTS PRATIQUES", {"circuit_type": "all", "category": "FFCO", "td_min": 1}),
    ("Méthode Fédérale", {"circuit_type": "all", "category": "FFCO", "td_min": 1}),
    ("circuits de couleur", {"circuit_type": "couleur", "category": "FFCO", "td_min": 1}),
    ("RTS_CO", {"circuit_type": "all", "category": "FFCO", "td_min": 1}),
    ("officials_handbook", {"circuit_type": "all", "category": "IOF", "td_min": 1}),
    ("woc_manual", {"circuit_type": "all", "category": "IOF", "td_min": 4}),
    ("PISTE_Swiss", {"circuit_type": "sprint", "category": "IOF", "td_min": 3}),
    ("Mémento_du_Corps_Arbitral", {"circuit_type": "all", "category": "FFCO", "td_min": 1}),
    ("règles_techniques", {"circuit_type": "all", "category": "FFCO", "td_min": 1}),
]


def _get_metadata(filename: str) -> Dict:
    for keyword, meta in _META_MAP:
        if keyword.lower() in filename.lower():
            return meta
    return {"circuit_type": "all", "category": "IOF", "td_min": 1}


def _extract_text(pdf_path: Path) -> str:
    """Extrait le texte brut d'un PDF via pymupdf."""
    doc = fitz.open(str(pdf_path))
    pages_text = []
    for page in doc:
        text = page.get_text()
        if text.strip():
            pages_text.append(text.strip())
    doc.close()
    return "\n\n".join(pages_text)


def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 200) -> List[str]:
    """Découpe le texte en chunks à fenêtre glissante."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if len(chunk) >= 100:  # filtrer les chunks trop courts
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


def _make_instruction(chunk: str, meta: Dict, source: str) -> str:
    """Génère une instruction de contexte pour LocalRAG."""
    category = meta.get("category", "IOF")
    circuit_type = meta.get("circuit_type", "all")
    label = f"{category} — {circuit_type}"
    # Extraire les 80 premiers chars comme topic
    topic = chunk[:80].replace("\n", " ").strip()
    return f"Règle de tracé [{label}] depuis {source}: {topic}"


def ingest_all(chunk_size: int = 800, overlap: int = 200) -> Dict:
    """
    Ingère tous les PDF des dossiers docs/ et docs controleur/.
    Écrit les chunks dans data/pdf_knowledge.jsonl.
    Retourne un rapport {indexed_chunks, sources, skipped}.
    """
    if not _FITZ_AVAILABLE:
        return {"error": "pymupdf non installé. Lancez : pip install pymupdf", "indexed_chunks": 0}

    OUTPUT_JSONL.parent.mkdir(parents=True, exist_ok=True)

    existing_sources: set = set()
    # Charger les sources déjà indexées pour ne pas dupliquer
    if OUTPUT_JSONL.exists():
        with open(OUTPUT_JSONL, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    existing_sources.add(item.get("source", ""))
                except json.JSONDecodeError:
                    pass

    total_chunks = 0
    sources_done = []
    skipped = []

    with open(OUTPUT_JSONL, "a", encoding="utf-8") as out:
        for docs_dir in DOCS_DIRS:
            if not docs_dir.exists():
                print(f"[WARNING] Dossier manquant : {docs_dir}")
                continue
            for pdf_path in sorted(docs_dir.glob("*.pdf")):
                filename = pdf_path.name
                if filename in existing_sources:
                    skipped.append(filename)
                    print(f"[SKIP] Déjà indexé : {filename}")
                    continue

                try:
                    print(f"[INFO] Extraction : {filename}")
                    text = _extract_text(pdf_path)
                    chunks = _chunk_text(text, chunk_size, overlap)
                    meta = _get_metadata(filename)

                    for chunk in chunks:
                        record = {
                            "instruction": _make_instruction(chunk, meta, filename),
                            "output": chunk,
                            "source": filename,
                            "source_type": "pdf_tracé",
                            "circuit_type": meta.get("circuit_type", "all"),
                            "category": meta.get("category", "IOF"),
                            "td_min": meta.get("td_min", 1),
                            "chunk_id": str(uuid.uuid4()),
                        }
                        out.write(json.dumps(record, ensure_ascii=False) + "\n")
                        total_chunks += 1

                    sources_done.append({"file": filename, "chunks": len(chunks)})
                    print(f"  → {len(chunks)} chunks indexés")

                except Exception as e:
                    print(f"[ERROR] {filename}: {e}")
                    skipped.append(filename)

    return {
        "indexed_chunks": total_chunks,
        "sources": sources_done,
        "skipped": skipped,
        "output_file": str(OUTPUT_JSONL),
    }


if __name__ == "__main__":
    result = ingest_all()
    print(f"\n✅ Ingestion terminée : {result['indexed_chunks']} chunks")
    for s in result["sources"]:
        print(f"   {s['file']} → {s['chunks']} chunks")
    if result["skipped"]:
        print(f"   Ignorés : {', '.join(result['skipped'])}")
