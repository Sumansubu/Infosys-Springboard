"""Pytest bootstrap: keep every test run away from the demo database.

``run_tests.py`` does the same for unittest discovery and ``tests/__init__.py``
covers direct ``python -m unittest tests.test_*`` runs. This file covers
developers who invoke ``pytest`` directly.
"""

from tests import TEST_DIR  # noqa: F401  (import configures the environment)
