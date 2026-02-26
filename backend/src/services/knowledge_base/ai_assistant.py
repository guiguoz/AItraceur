# =============================================
# Assistant IA pour le traceur
# Sprint 6: Base de connaissances RAG
# =============================================

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

# Import conditionnel pour OpenAI
try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from .rag_builder import RAGBuilder, SearchResult
from .local_rag import LocalRAG


# =============================================
# Types de données
# =============================================
@dataclass
class ConversationMessage:
    """Un message de conversation."""

    role: str  # "user", "assistant", "system"
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AssistantResponse:
    """Réponse de l'assistant."""

    answer: str
    sources: List[Dict] = field(default_factory=list)
    context_used: List[str] = field(default_factory=list)
    model: str = ""
    tokens_used: Optional[int] = None


# =============================================
# Prompt système
# =============================================
SYSTEM_PROMPT = """Tu es un assistant expert en traçage de parcours de course d'orientation.

Ton rôle est d'aider les traceurs de circuits de CO à:
- Analyser leurs circuits
- Détecter les problèmes
- Proposer des améliorations
- Répondre à leurs questions techniques

Tu connais:
- Les normes IOF (ISOM 2017, ISSprOM 2019)
- Les règles de sécurité
- Les bonnes pratiques de traçage
- Les techniques d'orientation

Tu as accès à une base de connaissances contenant:
- Des analyses de circuits Livelox
- Des articles techniques Vikazimut
- Des documents officiels (IOF, FFCO)

Réponds de manière claire et pédagogique. Si tu ne sais pas, dis-le.
"""


# =============================================
# Assistant IA
# =============================================
class AIAssistant:
    """
    Assistant IA pour répondre aux questions des traceurs.

    Utilise le RAG pour fournir des réponses contextualisées.
    """

    DEFAULT_MODEL = "gpt-4o-mini"
    MAX_TOKENS = 2000

    def __init__(
        self,
        rag_builder: RAGBuilder = None,
        model: str = None,
    ):
        """
        Initialise l'assistant.

        Args:
            rag_builder: Instance du RAGBuilder
            model: Modèle OpenAI à utiliser
        """
        self.rag = rag_builder
        self.model = model or self.DEFAULT_MODEL

        # Initialiser OpenAI
        if OPENAI_AVAILABLE and os.getenv("OPENAI_API_KEY"):
            self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        else:
            self.openai_client = None
            print("Attention: OPENAI_API_KEY non défini - utilisation du modèle local ffco-iof-v7")

        # Initialiser le RAG local (modèle fine-tuné ffco-iof-v7 via Ollama)
        try:
            self.local_rag = LocalRAG()
        except Exception as e:
            print(f"[WARNING] LocalRAG non disponible: {e}")
            self.local_rag = None

        # Historique de conversation
        self.conversation_history: List[ConversationMessage] = []

    def ask(
        self,
        question: str,
        context: Dict = None,
        n_sources: int = 5,
        use_rag: bool = True,
    ) -> AssistantResponse:
        """
        Pose une question à l'assistant.

        Args:
            question: Question de l'utilisateur
            context: Contexte additionnel (circuit, problèmes, etc.)
            n_sources: Nombre de sources à récupérer
            use_rag: Utiliser le RAG pour la recherche

        Returns:
            Réponse de l'assistant
        """
        # Ajouter la question à l'historique
        self.conversation_history.append(
            ConversationMessage(role="user", content=question)
        )

        # Préparer le contexte
        context_text = ""
        sources = []

        if use_rag and self.rag:
            # Rechercher dans la base de connaissances (ChromaDB/OpenAI embeddings)
            search_results = self.rag.search(question, n_results=n_sources)

            # Construire le contexte à partir des résultats
            context_parts = []
            for result in search_results:
                context_parts.append(f"[Source: {result.source}]\n{result.content}")
                sources.append(
                    {
                        "source": result.source,
                        "type": result.source_type,
                        "score": result.score,
                    }
                )

            if context_parts:
                context_text = "\n\n---\n\n".join(context_parts)

        # Enrichir avec le RAG local spécialisé CO/IOF (ffco-iof-v7)
        if use_rag and self.local_rag:
            try:
                local_answer, local_sources = self.local_rag.query(question)
                if local_answer and local_sources:
                    # Ajouter la réponse spécialisée CO comme contexte supplémentaire
                    context_text += f"\n\n---\n\n**Expertise CO/IOF (base spécialisée):**\n{local_answer}"
                    sources.extend(local_sources)
            except Exception:
                pass  # LocalRAG optionnel, ne bloque pas le flux principal

        # Ajouter le contexte du circuit si fourni
        if context:
            context_text += "\n\n---\n\n**Contexte du circuit:**\n"
            context_text += f"- Nom: {context.get('name', 'N/A')}\n"
            context_text += f"- Longueur: {context.get('length_meters', 'N/A')}m\n"
            context_text += f"- D+: {context.get('climb_meters', 'N/A')}m\n"
            context_text += f"- Postes: {context.get('number_of_controls', 'N/A')}\n"

            if context.get("problems"):
                context_text += "\n**Problèmes détectés:**\n"
                for p in context["problems"][:5]:
                    context_text += f"- {p.get('description', '')}\n"

        # Construire le prompt
        full_prompt = self._build_prompt(question, context_text)

        # Obtenir la réponse : OpenAI → ffco-iof-v7 → demo
        if self.openai_client:
            response = self._get_openai_response(full_prompt)
        elif self.local_rag:
            response = self._get_local_rag_response(question, sources)
        else:
            response = self._get_demo_response(question, sources)

        # Ajouter la réponse à l'historique
        self.conversation_history.append(
            ConversationMessage(role="assistant", content=response.answer)
        )

        # Limiter l'historique
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]

        return response

    def analyze_circuit(
        self,
        circuit_data: Dict,
        question: str = None,
    ) -> AssistantResponse:
        """
        Analyse un circuit spécifique.

        Args:
            circuit_data: Données du circuit
            question: Question optionnelle sur le circuit

        Returns:
            Analyse de l'assistant
        """
        # Construire le contexte
        context = {
            "name": circuit_data.get("name", "Circuit anonyme"),
            "length_meters": circuit_data.get("length_meters"),
            "climb_meters": circuit_data.get("climb_meters"),
            "number_of_controls": circuit_data.get("number_of_controls"),
            "category": circuit_data.get("category"),
            "technical_level": circuit_data.get("technical_level"),
            "problems": circuit_data.get("problems", []),
        }

        # Question par défaut
        if not question:
            question = (
                "Analyse ce circuit et donne-moi des conseils pour l'améliorer. "
                "Quels sont les points forts et les points faibles ?"
            )

        return self.ask(question, context=context)

    def get_similar_circuits(
        self,
        query: str,
        n_results: int = 3,
    ) -> List[Dict]:
        """
        Trouve des circuits similaires dans la base.

        Args:
            query: Description du circuit recherché
            n_results: Nombre de résultats

        Returns:
            Liste de circuits similaires
        """
        if not self.rag:
            return []

        results = self.rag.search(query, n_results=n_results)

        return [
            {
                "content": r.content[:500],  # Limiter la taille
                "source": r.source,
                "score": r.score,
            }
            for r in results
        ]

    def reset_conversation(self):
        """Reset l'historique de conversation."""
        self.conversation_history = []

    def _build_prompt(self, question: str, context: str) -> str:
        """Construit le prompt complet."""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Ajouter l'historique récent
        for msg in self.conversation_history[-10:]:
            messages.append(
                {
                    "role": msg.role,
                    "content": msg.content,
                }
            )

        # Ajouter le contexte RAG
        if context:
            context_msg = {
                "role": "system",
                "content": f"Voici des informations pertinentes de la base de connaissances:\n\n{context}",
            }
            messages.append(context_msg)

        # Ajouter la question actuelle
        messages.append({"role": "user", "content": question})

        return str(messages)  # Pour le mode demo

    def _get_openai_response(self, prompt) -> AssistantResponse:
        """Obtient une réponse d'OpenAI."""
        try:
            # Convertir le prompt en format messages
            import ast

            try:
                messages = ast.literal_eval(prompt)
            except:
                messages = [{"role": "user", "content": prompt}]

            response = self.openai_client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.MAX_TOKENS,
                temperature=0.7,
            )

            return AssistantResponse(
                answer=response.choices[0].message.content,
                model=response.model,
                tokens_used=response.usage.total_tokens if response.usage else None,
            )

        except Exception as e:
            return AssistantResponse(
                answer=f"Erreur: {str(e)}",
                model=self.model,
            )

    def _get_local_rag_response(
        self, question: str, sources: List[Dict]
    ) -> AssistantResponse:
        """Utilise le modèle local ffco-iof-v7 via LocalRAG (fallback sans OpenAI)."""
        try:
            answer, local_sources = self.local_rag.query(question)
            return AssistantResponse(
                answer=answer or "Je n'ai pas pu répondre à cette question.",
                sources=sources + local_sources,
                model="ffco-iof-v7 (local)",
            )
        except Exception:
            return self._get_demo_response(question, sources)

    def _get_demo_response(
        self, question: str, sources: List[Dict]
    ) -> AssistantResponse:
        """Mode demo sans API."""
        answer = f"""Mode démo - Clé API OpenAI non configurée.

Pour activer l'assistant, définissez la variable d'environnement OPENAI_API_KEY.

**Question posée:** {question}

**Sources disponibles:** {len(sources)}
"""

        if sources:
            answer += "\n**Sources:**\n"
            for s in sources[:3]:
                answer += f"- {s.get('source', 'N/A')}\n"

        answer += """

**Réponse en mode normal:**

L'assistant analyserait votre circuit en se basant sur:
1. Les normes ISOM/ISSprOM
2. Les bonnes pratiques de traçage
3. Les analyses de circuits similaires
4. Les documents officiels IOF/FFCO

Configurez OPENAI_API_KEY pour activer les réponses IA.
"""

        return AssistantResponse(
            answer=answer,
            sources=sources,
            model="demo",
        )


# =============================================
# Fonctions utilitaires
# =============================================
def create_assistant(
    openai_api_key: str = None,
    persist_directory: str = "./data/vector_store",
) -> AIAssistant:
    """
    Crée un assistant IA configuré.

    Args:
        openai_api_key: Clé API OpenAI
        persist_directory: Répertoire du vector store

    Returns:
        AIAssistant configuré
    """
    if openai_api_key:
        os.environ["OPENAI_API_KEY"] = openai_api_key

    # Créer le RAG
    rag = RAGBuilder(persist_directory=persist_directory)

    # Créer l'assistant
    return AIAssistant(rag_builder=rag)
