# =============================================
# Package generation
# Sprint 7: Génération de circuits
# RouteAI Integration (pathfinding, TSP)
# =============================================

from .graph_builder import GraphBuilder, NavigationGraph, Node, Edge
from .genetic_algo import (
    GeneticAlgorithm,
    GenerationConfig,
    GenerationResult,
    Circuit,
)
from .ai_generator import (
    AIGenerator,
    GenerationRequest,
    GeneratedCircuit,
    create_generator,
)
from .scorer import CircuitScorer, CircuitScore, ScoreBreakdown, compare_circuits

# RouteAI Integration
from .routeai_integration import (
    MapProcessor,
    PathFinder,
    TSPSolver,
    GridNode,
    PathResult,
    create_pathfinder,
    create_map_processor,
)

__all__ = [
    # Graph Builder
    "GraphBuilder",
    "NavigationGraph",
    "Node",
    "Edge",
    # Genetic Algorithm
    "GeneticAlgorithm",
    "GenerationConfig",
    "GenerationResult",
    "Circuit",
    # AI Generator
    "AIGenerator",
    "GenerationRequest",
    "GeneratedCircuit",
    "create_generator",
    # Scorer
    "CircuitScorer",
    "CircuitScore",
    "ScoreBreakdown",
    "compare_circuits",
    # RouteAI
    "MapProcessor",
    "PathFinder",
    "TSPSolver",
    "GridNode",
    "PathResult",
    "create_pathfinder",
    "create_map_processor",
]
