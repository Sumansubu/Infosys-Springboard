"""Test package bootstrap.

Imported for ``python -m unittest tests.test_*`` invocations, so direct test
runs also use a throwaway database instead of the developer's demo data.
``run_tests.py`` and ``conftest.py`` apply the same settings for their runners.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path


TEST_DIR = Path(tempfile.mkdtemp(prefix="finresearch-unittest-"))

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ["DATABASE_URL"] = ""
os.environ["SQLITE_DB_PATH"] = str(TEST_DIR / "test_documents.db")
os.environ["STORAGE_PROVIDER"] = "local"
os.environ["UPLOAD_DIR"] = str(TEST_DIR / "uploads")
os.environ["VECTOR_STORE_TYPE"] = "chroma"
os.environ["CHROMA_DB_DIR"] = str(TEST_DIR / "chroma_db")
os.environ["CHROMA_COLLECTION"] = "test_chunks"
os.environ["EMBEDDING_PROVIDER"] = "hashing"
os.environ["LLM_PROVIDER"] = "mock"

atexit.register(shutil.rmtree, TEST_DIR, ignore_errors=True)