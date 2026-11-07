"""Shared fixtures: an isolated app + SQLite DB + storage dir per test."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import jobs
from app.config import get_settings
from app.db import Base, get_db, make_engine
from app.llm.factory import set_provider_override
from app.main import create_app

FEATURE_DEFAULTS = {"grading_enabled": False, "grading_llm_approved": False, "identity_key": "", "lms_mode": "off",
                    "auth_mode": "dev", "storage_backend": "fs", "notice": ""}


def pytest_configure(config):
    """Before any (module-scoped) fixture runs: feature switches a developer turned
    on in backend/.env don't leak into tests."""
    s = get_settings()
    for name, value in FEATURE_DEFAULTS.items():
        setattr(s, name, value)


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    """Tests never call a real model, whatever backend/.env says: they would
    be slow, flaky, and would send data to an external service. Tests that
    need a model install a FakeProvider via set_provider_override()."""
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "none")
    monkeypatch.setattr(s, "llm_api_key", None)
    monkeypatch.setattr(s, "llm_model", None)
    monkeypatch.setattr(s, "llm_embed_model", None)  # local embedder only
    monkeypatch.setattr(s, "llm_no_retention", False)
    # Feature switches a developer may have turned on in backend/.env: tests start from the defaults.
    for name, value in FEATURE_DEFAULTS.items():
        monkeypatch.setattr(s, name, value)
    set_provider_override(None)
    yield
    set_provider_override(None)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(get_settings(), "storage_dir", tmp_path / "storage")
    # Jobs run synchronously inside the request, on the test database.
    monkeypatch.setattr(get_settings(), "worker_mode", "sync")
    monkeypatch.setattr(jobs, "session_factory", Session)
    app = create_app()

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    yield TestClient(app), Session
    set_provider_override(None)
