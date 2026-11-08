"""Shared pytest fixtures for all backend tests."""

import pytest
from app import db as db_module


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Redirect all DB and upload operations to a fresh temp directory."""
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(db_module, "UPLOAD_DIR", tmp_path / "uploads")
    db_module.init_db()
    return tmp_path
