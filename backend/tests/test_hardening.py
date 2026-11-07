"""Hardening (plan H.1 SSO, H.3 security)."""

from __future__ import annotations

import io
import time
import zipfile
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import auth
from app.config import get_settings
from app.upload_guard import RejectedUpload, check_office_zip
from tests.synth.render import to_docx
from tests.synth.specs import CSCI372, build
from tests.test_api_workflow import A


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in entries.items():
            z.writestr(n, d)
    return buf.getvalue()


def test_upload_guard():
    check_office_zip(to_docx(build(CSCI372)))  # a normal DOCX passes
    with pytest.raises(RejectedUpload, match="Macro"):
        check_office_zip(_zip({"[Content_Types].xml": b"<Types/>", "word/vbaProject.bin": b"x"}))
    with pytest.raises(RejectedUpload, match="Macro"):
        check_office_zip(_zip({"[Content_Types].xml": b"application/vnd.ms-word.document.macroEnabled.main+xml"}))
    with pytest.raises(RejectedUpload, match="bomb"):
        check_office_zip(_zip({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"0" * (60 * 1024 * 1024)}))
    with pytest.raises(RejectedUpload, match="valid"):
        check_office_zip(b"PK\x03\x04 not really a zip")


def test_macro_docx_rejected_at_upload(env):
    client, _ = env
    bad = _zip({"[Content_Types].xml": b"<Types/>", "word/vbaProject.bin": b"x"})
    r = client.post("/api/syllabi", headers=A, files={"file": ("syllabus.docx", bad, "application/octet-stream")})
    assert r.status_code == 415 and "Macro" in r.text


def test_audit_log_records_security_events(env):
    client, _ = env
    from tests.test_api_workflow import upload

    v = upload(client, CSCI372, "pdf")
    client.post(f"/api/course-versions/{v['id']}/lock", headers=A)
    client.get(f"/api/course-versions/{v['id']}/source", headers=A)
    actions = [e["action"] for e in client.get("/api/audit", headers=A).json()]
    assert {"syllabus_upload", "lock", "source_download"} <= set(actions)


# ---- SSO against a fake OIDC provider ------------------------------------- #

ISS = "https://idp.example.test"


class _FakeIdP:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.nonce = None
        self.email = "dr.someone@aurak.ac.ae"

    def jwks(self):
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        return {"keys": [{**jwk, "kid": "k1", "use": "sig", "alg": "RS256"}]}

    def id_token(self, aud):
        now = int(time.time())
        return jwt.encode({"iss": ISS, "aud": aud, "sub": "123", "email": self.email, "name": "Dr Someone",
                           "iat": now, "exp": now + 300, "nonce": self.nonce}, self.key, algorithm="RS256",
                          headers={"kid": "k1"})


@pytest.fixture()
def sso(env, monkeypatch):
    client, _ = env
    s = get_settings()
    for k, v in {"auth_mode": "sso", "oidc_issuer": ISS, "oidc_client_id": "eduforge", "session_secret": "x" * 40,
                 "oidc_allowed_domains": ["aurak.ac.ae"], "frontend_url": "http://ui.test"}.items():
        monkeypatch.setattr(s, k, v)
    idp = _FakeIdP()
    meta = {"issuer": ISS, "authorization_endpoint": f"{ISS}/authorize", "token_endpoint": f"{ISS}/token",
            "jwks_uri": f"{ISS}/jwks"}
    monkeypatch.setattr(auth, "_discovery", lambda issuer: meta)

    class _Jwks:
        def get_signing_key_from_jwt(self, token):
            return jwt.PyJWK(idp.jwks()["keys"][0])

    monkeypatch.setattr(auth, "_jwks_client", lambda uri: _Jwks())

    class _Resp:
        status_code = 200

        def json(self):
            return {"id_token": idp.id_token("eduforge")}

    monkeypatch.setattr(auth.httpx, "post", lambda *a, **k: _Resp())
    return client, idp


def test_sso_login_flow(sso):
    client, idp = sso
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers=A).status_code == 401  # the dev header no longer works
    r = client.get("/api/auth/login?next=/v/1", follow_redirects=False)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["client_id"] == ["eduforge"]
    idp.nonce = q["nonce"][0]
    cb = client.get(f"/api/auth/callback?code=abc&state={q['state'][0]}", follow_redirects=False)
    assert cb.status_code == 302 and cb.headers["location"] == "http://ui.test/v/1", cb.text
    me = client.get("/api/me").json()
    assert me["email"] == "dr.someone@aurak.ac.ae" and me["name"] == "Dr Someone"
    assert client.post("/api/auth/logout").status_code == 204


def test_sso_rejects_wrong_state_nonce_and_domain(sso):
    client, idp = sso
    q = parse_qs(urlparse(client.get("/api/auth/login", follow_redirects=False).headers["location"]).query)
    assert client.get("/api/auth/callback?code=abc&state=forged", follow_redirects=False).status_code == 400
    idp.nonce = "something-else"
    assert client.get(f"/api/auth/callback?code=abc&state={q['state'][0]}", follow_redirects=False).status_code == 401
    idp.nonce = q["nonce"][0]
    idp.email = "student@gmail.com"
    assert client.get(f"/api/auth/callback?code=abc&state={q['state'][0]}", follow_redirects=False).status_code == 403
