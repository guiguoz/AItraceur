# =============================================
# Script d'ingestion des documents officiels
# =============================================
import os
import sys
from pathlib import Path

# Ajouter le dossier parent au path pour les imports
sys.path.append(str(Path(__file__).parent.parent))

from src.services.knowledge_base.rag_builder import RAGBuilder, KnowledgeChunk
from src.services.knowledge_base.document_loader import DocumentLoader, OfficialDocuments

def ingest_documents():
    """
    Charge et indexe les documents officiels définis dans OfficialDocuments.
    Cherche d'abord en local dans ./data/documents/, sinon utilise l'URL.
    """
    print("🚀 Démarrage de l'ingestion des documents officiels...")
    
    # Configuration
    docs_dir = Path("data/documents")
    docs_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialiser les services
    rag = RAGBuilder(persist_directory="./data/vector_store")
    loader = DocumentLoader()
    
    # Récupérer la liste des documents
    all_docs = {**OfficialDocuments.IOF_DOCUMENTS, **OfficialDocuments.FFCO_DOCUMENTS}

    # Ajout de la ressource externe (GPT)
    all_docs["gpt_orienteringsteknik"] = {
        "title": "Lær orienteringsteknik til orienteringsløb (GPT)",
        "url": "https://chatgpt.com/g/g-6761eeab18448191b72a1cef7796a2aa-laer-orienteringsteknik-til-orienteringslob",
        "description": "Assistant GPT spécialisé dans les techniques d'orientation (Page de présentation)."
    }
    
    total_chunks = 0
    
    for key, doc_info in all_docs.items():
        print(f"\n📄 Traitement de : {doc_info['title']}")
        
        # 1. Essayer de trouver le fichier localement
        # On cherche des fichiers qui contiennent la clé ou le titre
        local_file = None
        # Nouvelle logique : vérifier un nom de fichier explicite dans la configuration
        if doc_info.get("filename"):
            potential_file = docs_dir / doc_info["filename"]
            if potential_file.exists():
                local_file = potential_file

        # Logique de secours si pas de nom de fichier explicite ou fichier non trouvé
        if not local_file:
            for f in docs_dir.glob("*"):
                if key in f.name.lower() or doc_info['title'][:10] in f.name:
                    local_file = f
                    break
        
        document = None
        
        # 2. Chargement
        if local_file:
            print(f"   📂 Fichier local trouvé : {local_file}")
            document = loader.load_file(local_file)
        elif doc_info.get("url") and doc_info["url"] != "local":
            print(f"   🌐 Téléchargement depuis : {doc_info['url']}")
            # Note: load_url est fait pour le HTML, pour un PDF distant il faudrait le télécharger d'abord
            # Ici on simplifie en supposant que l'utilisateur a mis les PDF dans data/documents
            if doc_info["url"].endswith(".pdf"):
                print("   ⚠️ Pour les PDF, veuillez télécharger le fichier et le placer dans data/documents/")
                continue
            else:
                document = loader.load_url(doc_info["url"])
        else:
            print("   ❌ Aucun fichier local ni URL valide trouvés.")
            continue
            
        if not document:
            print("   ❌ Échec du chargement du document.")
            continue
            
        # 3. Chunking
        chunks = loader.chunk_document(document)
        print(f"   ✂️ Découpé en {len(chunks)} morceaux.")
        
        # 4. Indexation
        knowledge_chunks = []
        for c in chunks:
            # Enrichir les métadonnées
            meta = c.metadata.copy()
            meta.update({
                "doc_key": key,
                "official_title": doc_info['title'],
                "description": doc_info['description']
            })
            
            k_chunk = KnowledgeChunk(
                chunk_id=c.chunk_id,
                content=c.content,
                source=doc_info['title'], # Utiliser le titre officiel comme source
                source_type="official_document",
                metadata=meta
            )
            knowledge_chunks.append(k_chunk)
            
        success_count = rag.add_chunks(knowledge_chunks)
        total_chunks += success_count
        print(f"   ✅ {success_count} chunks indexés.")

    print(f"\n✨ Terminé ! Total chunks indexés : {total_chunks}")
    stats = rag.get_stats()
    print(f"📊 État de la base : {stats}")

if __name__ == "__main__":
    ingest_documents()
