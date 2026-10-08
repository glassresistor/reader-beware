"""Pytest configuration so `import beware` works when running from the repo."""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__)) + '/..'
sys.path.insert(0, os.path.abspath(REPO_ROOT))
