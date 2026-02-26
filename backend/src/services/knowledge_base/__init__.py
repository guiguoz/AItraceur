# =============================================
# Package knowledge_base
# Sprint 6: Base de connaissances RAG
# =============================================

from .document_loader import DocumentLoader, Document, DocumentChunk, OfficialDocuments
from .rag_builder import (
    RAGBuilder,
    KnowledgeChunk,
    SearchResult,
    initialize_knowledge_base,
)
from .ai_assistant import AIAssistant, AssistantResponse, create_assistant

# Scraper imports
from .scrapers.livelox import (
    LiveloxScraper,
    LiveloxEvent,
    LiveloxResult,
    export_event_to_text,
)
from .scrapers.vikazimut import VikazimutScraper, VikazimutAnalysis, VikazimutCircuit
from .scrapers.routegadget import (
    RouteGadgetScraper,
    RouteGadgetEvent,
    RouteGadgetCourse,
    RouteGadgetTrack,
    RouteAnalyzer,
    export_track_to_text,
)

__all__ = [
    # Document Loader
    "DocumentLoader",
    "Document",
    "DocumentChunk",
    "OfficialDocuments",
    # RAG Builder
    "RAGBuilder",
    "KnowledgeChunk",
    "SearchResult",
    "initialize_knowledge_base",
    # AI Assistant
    "AIAssistant",
    "AssistantResponse",
    "create_assistant",
    # Scrapers
    "LiveloxScraper",
    "LiveloxEvent",
    "LiveloxResult",
    "export_event_to_text",
    "VikazimutScraper",
    "VikazimutAnalysis",
    "VikazimutCircuit",
    # RouteGadget
    "RouteGadgetScraper",
    "RouteGadgetEvent",
    "RouteGadgetCourse",
    "RouteGadgetTrack",
    "RouteAnalyzer",
    "export_track_to_text",
]
