"""Tests d'architecture du moteur v2 (backend/src/aitraceur/).

Ces tests vérifient les invariants structurels définis dans docs/plan/03_REGLES_DE_TRAVAIL.md §8.
Ils s'appliquent à tous les fichiers .py de src/aitraceur/ sauf evalbench/replay_v1.py,
autorisé par exception à importer src.main (plan §0.8).
"""
import ast
from pathlib import Path

AITRACEUR_SRC = Path(__file__).parent.parent.parent / "src" / "aitraceur"

# Exception explicite : replay_v1.py est autorisé à importer src.main
REPLAY_EXCEPTION = AITRACEUR_SRC / "evalbench" / "replay_v1.py"

FORBIDDEN_IMPORTS = {
    "fastapi", "sqlalchemy", "requests",
    "src.services", "src.api", "src.main", "src.aitraceur_proto",
}


def _python_files(root: Path, exclude: Path | None = None) -> list[Path]:
    return [
        p for p in root.rglob("*.py")
        if not any(part == "__pycache__" for part in p.parts)
        and p != exclude
    ]


def _top_level_module(name: str) -> str:
    return name.split(".")[0]


def _full_module(name: str) -> str:
    return name


def _collect_imports(path: Path) -> list[str]:
    """Renvoie les noms complets importés (top-level ou dotted)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_engine_has_no_forbidden_imports() -> None:
    """Aucun fichier de src/aitraceur/ n'importe fastapi, sqlalchemy, requests,
    src.services, src.api, src.main ou src.aitraceur_proto.
    Exception : evalbench/replay_v1.py peut importer src.main.
    """
    violations: list[str] = []
    for py_file in _python_files(AITRACEUR_SRC, exclude=REPLAY_EXCEPTION):
        for imp in _collect_imports(py_file):
            top = _top_level_module(imp)
            full = _full_module(imp)
            for forbidden in FORBIDDEN_IMPORTS:
                if full == forbidden or full.startswith(forbidden + ".") or top == forbidden:
                    rel = py_file.relative_to(AITRACEUR_SRC.parent.parent)
                    violations.append(f"{rel}: importe '{imp}' (interdit : '{forbidden}')")
    assert not violations, "Imports interdits détectés :\n" + "\n".join(violations)


def test_no_global_random() -> None:
    """Aucun appel random.<fn>( ni np.random.<fn>( hors default_rng() / Random(
    dans src/aitraceur/.
    """
    import re

    # Cherche random.xxx( ou np.random.xxx( mais pas random.Random( ni np.random.default_rng(
    pattern = re.compile(
        r"\b(?:random\.|np\.random\.)(\w+)\s*\(",
    )
    allowed_suffixes = {"Random", "default_rng", "seed"}  # constructeurs/initialiseurs acceptés

    violations: list[str] = []
    for py_file in _python_files(AITRACEUR_SRC):
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(source.splitlines(), start=1):
            for m in pattern.finditer(line):
                fn = m.group(1)
                if fn not in allowed_suffixes:
                    rel = py_file.relative_to(AITRACEUR_SRC.parent.parent)
                    violations.append(f"{rel}:{lineno}: appel aléatoire global '{m.group()}'")
    assert not violations, "Appels aléatoires globaux détectés :\n" + "\n".join(violations)


def test_no_silent_except() -> None:
    """Aucun bloc except dont le corps est uniquement pass dans src/aitraceur/."""
    violations: list[str] = []
    for py_file in _python_files(AITRACEUR_SRC):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                body = node.body
                if len(body) == 1 and isinstance(body[0], ast.Pass):
                    rel = py_file.relative_to(AITRACEUR_SRC.parent.parent)
                    violations.append(f"{rel}:{node.lineno}: except silencieux (pass seul)")
    assert not violations, "Excepts silencieux détectés :\n" + "\n".join(violations)
