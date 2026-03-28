"""Couche 6 — Génération de parcours."""
from .constructive import generate_initial_course
from .local_opt import improve_course_local

__all__ = ["generate_initial_course", "improve_course_local"]
