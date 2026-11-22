"""Automated Test Runner for Multi-Agent Financial Research System.

Executes all unit, integration, and end-to-end tests across the test suite.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


def configure_isolated_test_environment() -> Path:
    """Point every persistence layer at a throwaway directory.

    The suite exercises the real repositories, vector store and file storage, so
    without this it writes workspaces, documents, metrics and research messages
    into the developer's demo database. Environment variables must be set before
    any application module (and therefore ``get_settings``) is imported.
    """
    test_dir = Path(tempfile.mkdtemp(prefix="finresearch-tests-"))

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    # Never touch the demo SQLite/PostgreSQL database.
    os.environ["DATABASE_URL"] = ""
    os.environ["SQLITE_DB_PATH"] = str(test_dir / "test_documents.db")

    # Isolate uploads and the vector index too.
    os.environ["STORAGE_PROVIDER"] = "local"
    os.environ["UPLOAD_DIR"] = str(test_dir / "uploads")
    os.environ["VECTOR_STORE_TYPE"] = "chroma"
    os.environ["CHROMA_DB_DIR"] = str(test_dir / "chroma_db")
    os.environ["CHROMA_COLLECTION"] = "test_chunks"

    # Deterministic, offline model behaviour.
    os.environ["EMBEDDING_PROVIDER"] = "hashing"
    os.environ["LLM_PROVIDER"] = "mock"
    return test_dir

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def run_all_tests() -> bool:
    test_dir = configure_isolated_test_environment()
    print(f"Isolated test data directory: {test_dir}", flush=True)
    print("=" * 70)
    print("Multi-Agent Financial Research System — Automated Test Suite")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite = loader.discover(start_dir="tests", pattern="test_*.py")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    print(f"Total Tests Run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    print("=" * 70)

    shutil.rmtree(test_dir, ignore_errors=True)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
