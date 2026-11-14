"""Analyse les imports tiers dans backend/src/**/*.py et les compare aux paquets déclarés."""
import ast
import sys
import sysconfig
from pathlib import Path

# Noms de modules de la bibliothèque standard (Python 3.11)
STDLIB = set(sys.stdlib_module_names)  # disponible depuis Python 3.10

# Mappage module → paquet PyPI (quand le nom diffère)
MODULE_TO_PACKAGE = {
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "PIL": "Pillow",
    "yaml": "PyYAML",
    "dotenv": "python-dotenv",
    "magic": "python-magic",
    "fitz": "pymupdf",
    "sqlalchemy": "sqlalchemy",
    "pydantic": "pydantic",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "httpx": "httpx",
    "structlog": "structlog",
    "psycopg2": "psycopg2-binary",
    "asyncpg": "asyncpg",
    "alembic": "alembic",
    "multipart": "python-multipart",
    "srtm": "srtm.py",
    "sentence_transformers": "sentence-transformers",
    "chromadb": "chromadb",
}


def _top_level(name: str) -> str:
    return name.split(".")[0]


def _collect_imports(path: Path) -> list[tuple[str, bool]]:
    """Renvoie (top_level_module, protected_by_try)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []

    results = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # Chercher si le nœud est enfant direct d'un try/except
            protected = False
            for ancestor in ast.walk(tree):
                if isinstance(ancestor, ast.ExceptHandler):
                    for child in ast.walk(ancestor):
                        if child is node:
                            protected = True
            if isinstance(node, ast.Import):
                for alias in node.names:
                    results.append((_top_level(alias.name), protected))
            elif isinstance(node, ast.ImportFrom) and node.module:
                results.append((_top_level(node.module), protected))
    return results


def _declared_packages(req_file: Path) -> set[str]:
    """Extrait les noms de paquets d'un requirements.txt (ignore commentaires et options)."""
    packages = set()
    if not req_file.exists():
        return packages
    for line in req_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        name = line.split(">=")[0].split("==")[0].split("<=")[0].split("!=")[0].strip()
        packages.add(name.lower())
    return packages


def main() -> None:
    root = Path(__file__).parent.parent  # backend/
    src_dir = root / "src"
    all_req = root / "requirements.txt"

    declared = _declared_packages(all_req)
    # Normalisation : on compare en minuscules, tirets et underscores confondus
    declared_norm = {p.replace("-", "_") for p in declared} | {p.replace("_", "-") for p in declared}

    # Accumuler par module : fichiers qui l'importent, est-il protégé dans tous ses fichiers ?
    module_files: dict[str, list[str]] = {}
    module_protected: dict[str, list[bool]] = {}

    for py_file in sorted(src_dir.rglob("*.py")):
        rel = py_file.relative_to(root)
        for mod, prot in _collect_imports(py_file):
            if mod in STDLIB or mod.startswith("src") or mod == "__future__":
                continue
            module_files.setdefault(mod, []).append(str(rel))
            module_protected.setdefault(mod, []).append(prot)

    # Affichage tableau
    print(f"{'Module':<30} {'Fichiers':>7}  {'Déclaré':>8}  {'Protégé try':>12}  Exemple de fichier")
    print("-" * 100)
    for mod in sorted(module_files):
        pkg_name = MODULE_TO_PACKAGE.get(mod, mod).lower()
        pkg_norm = pkg_name.replace("-", "_")
        is_declared = pkg_name in declared or pkg_name in declared_norm or pkg_norm in declared_norm
        all_protected = all(module_protected[mod])
        n = len(module_files[mod])
        status_d = "oui" if is_declared else "NON"
        status_p = "oui (tous)" if all_protected else ("partiel" if any(module_protected[mod]) else "non")
        example = module_files[mod][0]
        print(f"{mod:<30} {n:>7}  {status_d:>8}  {status_p:>12}  {example}")


if __name__ == "__main__":
    main()
