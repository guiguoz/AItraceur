# =============================================
# Package d'optimisation
# Sprint 4: Détection de problèmes
# Sprint 5: Calcul de routes et optimisation
# =============================================

from .detector import (
    ProblemDetector,
    AnalysisResult,
    Problem,
    calculate_distance_meters,
)

from .route_calculator import (
    RouteCalculator,
    PositionOptimizer,
    Route,
    Waypoint,
    RouteAnalysis,
    estimate_circuit_time,
)

__all__ = [
    # Detector
    "ProblemDetector",
    "AnalysisResult",
    "Problem",
    "calculate_distance_meters",
    # Route Calculator
    "RouteCalculator",
    "PositionOptimizer",
    "Route",
    "Waypoint",
    "RouteAnalysis",
    "estimate_circuit_time",
]
