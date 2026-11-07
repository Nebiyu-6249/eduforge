"""Hosted-prototype settings: AUTH_MODE=open and STORAGE_BACKEND=db."""

from __future__ import annotations

import shutil

from sqlalchemy import select

from app.config import get_settings
from app.models import StoredBlob
from tests.synth.specs import STAT100
from tests.test_api_workflow import upload


def test_open_mode_needs_no_sign_in(env, monkeypatch):
    client, _ = env
    s = get_settings()
    monkeypatch.setattr(s, "auth_mode", "open")
    monkeypatch.setattr(s, "notice", "Prototype: use made-up data only.")
    cfg = client.get("/api/auth/config").json()
    assert cfg["mode"] == "open" and cfg["notice"].startswith("Prototype")
    me = client.get("/api/me").json()  # no header, no cookie
    assert me["email"] == s.open_access_email and me["name"] == "Demo Faculty"
    # Everyone is the same shared account, whatever they send.
    assert client.get("/api/me", headers={"X-Dev-User": "someone@else.edu"}).json()["email"] == s.open_access_email


def test_db_storage_survives_a_wiped_disk(env, monkeypatch):
    client, Session = env
    s = get_settings()
    monkeypatch.setattr(s, "storage_backend", "db")
    v = upload(client, STAT100, "pdf")
    with Session() as db:
        assert db.scalar(select(StoredBlob)) is not None
    shutil.rmtree(s.storage_dir, ignore_errors=True)  # what a free host does on restart
    from tests.test_api_workflow import A

    src = client.get(f"/api/course-versions/{v['id']}/source", headers=A)
    assert src.status_code == 200 and src.content[:5] == b"%PDF-"
    page = client.get(f"/api/course-versions/{v['id']}/source/pages/1", headers=A)
    assert page.status_code == 200 and page.headers["content-type"] == "image/png"
