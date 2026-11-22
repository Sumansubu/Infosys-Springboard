"""Build the submission archive with both the backend and the frontend.

Run from anywhere:

    python package_submission.py

The archive is written next to this folder as
``Infosys-Springboard-submission.zip`` and contains ``Engine/``, ``Frontend/``,
``docs/`` and the root project files. Runtime-only artifacts (virtualenv, node
modules, build output, local databases, vector indexes, logs) are excluded so
the archive stays small and reproducible.
"""

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT.parent / "Infosys-Springboard-submission.zip"

EXCLUDED_DIRS = {
    "venv",
    ".venv",
    "env",
    "node_modules",
    "dist",
    "dist-ssr",
    "__pycache__",
    "chroma_db",
    "qdrant_storage",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".vite",
    ".turbo",
    "htmlcov",
    ".idea",
    ".vscode",
}

EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3", ".tmp"}

EXCLUDED_FILES = {".DS_Store", "Thumbs.db"}

# Runtime uploads are user data; ship only the tracked placeholder and the
# curated seed filings that the demo session relies on.
UPLOAD_DIR = ROOT / "Engine" / "uploads"
SEED_DOCS_DIR = ROOT / "Engine" / "seed_documents"


def include(path: Path) -> bool:
    rel = path.relative_to(ROOT)

    if any(part in EXCLUDED_DIRS for part in rel.parts):
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if path.name in EXCLUDED_FILES:
        return False

    # Keep template env files, never real ones.
    if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
        return False

    if UPLOAD_DIR in path.parents:
        return path.name == ".gitkeep"

    return True


def main() -> int:
    if not (ROOT / "Frontend" / "package.json").exists():
        print("ERROR: Frontend/package.json not found; refusing to build an incomplete archive.")
        return 1

    required = [
        ROOT / "Frontend" / "src" / "App.jsx",
        ROOT / "Frontend" / "src" / "pages" / "ConversationalResearch.jsx",
        ROOT / "Frontend" / "src" / "components" / "comparison" / "ComparisonPanel.jsx",
        ROOT / "Engine" / "main.py",
    ]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.exists()]
    if missing:
        print("ERROR: missing required project files:")
        for name in missing:
            print(f"  - {name}")
        return 1

    files = sorted(
        path for path in ROOT.rglob("*") if path.is_file() and include(path)
    )

    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=str(path.relative_to(ROOT)).replace("\\", "/"))

    with zipfile.ZipFile(OUTPUT) as archive:
        names = set(archive.namelist())
        missing_in_zip = [
            str(p.relative_to(ROOT)).replace("\\", "/")
            for p in required
            if str(p.relative_to(ROOT)).replace("\\", "/") not in names
        ]

    if missing_in_zip:
        print("ERROR: archive is incomplete:")
        for name in missing_in_zip:
            print(f"  - {name}")
        return 1

    size_mb = OUTPUT.stat().st_size / (1024 * 1024)
    print(f"Archive: {OUTPUT}")
    print(f"Files:   {len(files)}")
    print(f"Size:    {size_mb:.1f} MB")
    print("Verified: Engine/, Frontend/App.jsx, ConversationalResearch.jsx, ComparisonPanel.jsx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
