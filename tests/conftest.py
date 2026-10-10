"""Shared fixtures for the beware test suite."""

import pytest


@pytest.fixture
def out(tmp_path):
    """Unique output path per test so tests never clobber each other."""
    return str(tmp_path / "output")
