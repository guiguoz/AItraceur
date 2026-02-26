# =============================================
# Builder RAG - Index vectoriel
# Sprint 6: Base de connaissances RAG
# =============================================

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

# Import conditionnel pour les embeddings
try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# Import pour ChromaDB
try:
    import chromadb
    from chromadb.config import Settings

    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False


# =============================================
# Types de données
# =============================================
@dataclass
class KnowledgeChunk:
    """Un chunk avec son embedding."""

    chunk_id: str
    content: str
    source: str
    source_type: str  # "livelox", "vikazimut", "document", "circuit"
    metadata: Dict = field(default_factory=dict)
    embedding: Optional[List[float]] = None


@dataclass
class SearchResult:
    """Résultat de recherche."""

    chunk_id: str
    content: str
    source: str
    source_type: str
    score: float  # Similarité (0-1)
    metadata: Dict = field(default_factory=dict)


# =============================================
# Builder RAG
# =============================================
class RAGBuilder:
    """
    Construit et gère l'index vectoriel pour le RAG.

    Utilise:
    - OpenAI pour les embeddings (text-embedding-ada-002)
    - ChromaDB pour le stockage vectoriel
    """

    EMBEDDING_MODEL = "text-embedding-ada-002"
    COLLECTION_NAME = "aitraceur_knowledge"

    def __init__(
        self,
        persist_directory: str = "./data/vector_store",
        embedding_model: str = None,
    ):
        """
        Initialise le builder RAG.

        Args:
            persist_directory: Répertoire de stockage
            embedding_model: Modèle d'embedding à utiliser
        """
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)

        self.embedding_model = embedding_model or self.EMBEDDING_MODEL
        self.client = None
        self.collection = None

        # Initialiser OpenAI si disponible
        if OPENAI_AVAILABLE and os.getenv("OPENAI_API_KEY"):
            self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        else:
            self.openai_client = None
            print("Attention: OPENAI_API_KEY non défini - mode demo")

        # Initialiser ChromaDB
        if CHROMA_AVAILABLE:
            self._init_chroma()
        else:
            print("Attention: ChromaDB non installé - mode demo")

    def _init_chroma(self):
        """Initialise ChromaDB."""
        try:
            self.client = chromadb.PersistentClient(
                path=str(self.persist_directory),
                settings=Settings(anonymized_telemetry=False),
            )

            # Créer ou récupérer la collection
            self.collection = self.client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"description": "Base de connaissances AItraceur"},
            )
        except Exception as e:
            print(f"Erreur initialisation ChromaDB: {e}")
            self.client = None

    def add_chunk(self, chunk: KnowledgeChunk) -> bool:
        """
        Ajoute un chunk à l'index.

        Args:
            chunk: Chunk à ajouter

        Returns:
            True si succès
        """
        # Générer l'embedding
        if self.openai_client:
            embedding = self._get_embedding(chunk.content)
            chunk.embedding = embedding
        else:
            # Mode demo: pas d'embedding
            embedding = None

        # Ajouter à ChromaDB
        if self.collection:
            try:
                self.collection.add(
                    ids=[chunk.chunk_id],
                    documents=[chunk.content],
                    embeddings=[embedding] if embedding else None,
                    metadatas=[
                        {
                            "source": chunk.source,
                            "source_type": chunk.source_type,
                            **chunk.metadata,
                        }
                    ],
                )
                return True
            except Exception as e:
                print(f"Erreur ajout chunk: {e}")
                return False

        return False

    def add_chunks(self, chunks: List[KnowledgeChunk]) -> int:
        """
        Ajoute plusieurs chunks.

        Args:
            chunks: Liste de chunks

        Returns:
            Nombre de chunks ajoutés
        """
        count = 0
        for chunk in chunks:
            if self.add_chunk(chunk):
                count += 1
        return count

    def add_texts(
        self,
        texts: List[str],
        sources: List[str],
        source_type: str,
        metadata: List[Dict] = None,
    ) -> int:
        """
        Ajoute des textes directement.

        Args:
            texts: Liste de textes
            sources: Liste des sources correspondantes
            source_type: Type de source
            metadata: Métadonnées optionnelles

        Returns:
            Nombre de textes ajoutés
        """
        chunks = []

        for i, text in enumerate(texts):
            chunk = KnowledgeChunk(
                chunk_id=str(uuid.uuid4()),
                content=text,
                source=sources[i] if i < len(sources) else "unknown",
                source_type=source_type,
                metadata=metadata[i] if metadata and i < len(metadata) else {},
            )
            chunks.append(chunk)

        return self.add_chunks(chunks)

    def search(
        self,
        query: str,
        n_results: int = 5,
        filter_metadata: Dict = None,
    ) -> List[SearchResult]:
        """
        Recherche les chunks les plus similaires.

        Args:
            query: Requête de recherche
            n_results: Nombre de résultats
            filter_metadata: Filtres sur les métadonnées

        Returns:
            Liste de résultats triés par similarité
        """
        if not self.collection:
            return []

        # Obtenir l'embedding de la requête
        if self.openai_client:
            query_embedding = self._get_embedding(query)
        else:
            # Mode demo: retourner des résultats vides
            return []

        # Rechercher
        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=filter_metadata,
            )

            # Parser les résultats
            search_results = []

            if results and results.get("ids"):
                for i, chunk_id in enumerate(results["ids"][0]):
                    idx = results["documents"][0][i]
                    metadata = (
                        results["metadatas"][0][i] if results.get("metadatas") else {}
                    )
                    distance = (
                        results["distances"][0][i] if results.get("distances") else 0
                    )

                    # Convertir distance en score de similarité (0-1)
                    score = 1 - distance if distance else 0

                    search_results.append(
                        SearchResult(
                            chunk_id=chunk_id,
                            content=results["documents"][0][i],
                            source=metadata.get("source", ""),
                            source_type=metadata.get("source_type", ""),
                            score=score,
                            metadata=metadata,
                        )
                    )

            return search_results

        except Exception as e:
            print(f"Erreur recherche: {e}")
            return []

    def get_stats(self) -> Dict:
        """Retourne les statistiques de l'index."""
        if not self.collection:
            return {
                "status": "not_initialized",
                "total_chunks": 0,
            }

        try:
            count = self.collection.count()
            return {
                "status": "ready",
                "total_chunks": count,
                "persist_directory": str(self.persist_directory),
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
            }

    def delete_by_source(self, source: str) -> int:
        """
        Supprime tous les chunks d'une source.

        Args:
            source: Source à supprimer

        Returns:
            Nombre de chunks supprimés
        """
        if not self.collection:
            return 0

        try:
            # Récupérer les IDs à supprimer
            results = self.collection.get(where={"source": source})

            if results and results.get("ids"):
                self.collection.delete(ids=results["ids"])
                return len(results["ids"])
        except Exception as e:
            print(f"Erreur suppression: {e}")

        return 0

    def clear(self) -> bool:
        """Supprime tous les chunks."""
        if not self.collection:
            return False

        try:
            self.client.delete_collection(self.COLLECTION_NAME)
            self._init_chroma()
            return True
        except Exception as e:
            print(f"Erreur clear: {e}")
            return False

    def _get_embedding(self, text: str) -> List[float]:
        """Calcule l'embedding d'un texte."""
        if not self.openai_client:
            return []

        try:
            response = self.openai_client.embeddings.create(
                model=self.embedding_model,
                input=text,
            )
            return response.data[0].embedding
        except Exception as e:
            print(f"Erreur embedding: {e}")
            return []


# =============================================
# Helper pour initialiser la base
# =============================================
def initialize_knowledge_base(
    documents_path: str = None,
    openai_api_key: str = None,
) -> RAGBuilder:
    """
    Initialise la base de connaissances.

    Args:
        documents_path: Chemin vers les documents
        openai_api_key: Clé API OpenAI

    Returns:
        RAGBuilder initialisé
    """
    # Configurer la clé API
    if openai_api_key:
        os.environ["OPENAI_API_KEY"] = openai_api_key

    # Créer le builder
    builder = RAGBuilder()

    # Charger les documents si un chemin est fourni
    if documents_path:
        from .document_loader import DocumentLoader

        loader = DocumentLoader()
        docs = loader.load_directory(documents_path)

        for doc in loader.documents:
            chunks = loader.chunk_document(doc)
            builder.add_chunks(
                [
                    KnowledgeChunk(
                        chunk_id=c.chunk_id,
                        content=c.content,
                        source=doc.source,
                        source_type=doc.doc_type,
                        metadata=doc.metadata,
                    )
                    for c in chunks
                ]
            )

    return builder
