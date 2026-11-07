"""Faculty identity. Faculty are the only users in Phases 1–2 (D3); no admin role (D2).

AUTH_MODE:

* ``dev``: the X-Dev-User header (an email) identifies the faculty member; the
  account is created on first use. Local development and tests only.
* ``open``: no sign-in at all; every request is one shared demo faculty account
  (OPEN_ACCESS_EMAIL / OPEN_ACCESS_NAME). For a hosted prototype only, until the
  university plugs in its own sign-in.
* ``sso``: University SSO via OpenID Connect (plan H.1). Authorization-code
  flow with PKCE against OIDC_ISSUER (discovered from
  /.well-known/openid-configuration). The ID token is verified against the
  provider's JWKS (signature, issuer, audience, expiry, nonce). The session is
  a signed, httpOnly, SameSite=Lax cookie holding the faculty id. SAML-only
  IdPs can sit behind an OIDC bridge (e.g. Azure AD / Entra already speaks OIDC).
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import Faculty

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SESSION_COOKIE = "eduforge_session"
FLOW_COOKIE = "eduforge_oidc"
SESSION_MAX_AGE = 8 * 3600  # one working day

router = APIRouter(prefix="/api/auth")


def _serializer(salt: str) -> URLSafeTimedSerializer:
    secret = get_settings().session_secret
    if not secret:
        raise HTTPException(500, "SESSION_SECRET is not set.")
    return URLSafeTimedSerializer(secret, salt=salt)


def _get_or_create(db: Session, email: str, name: str | None) -> Faculty:
    email = email.strip().lower()
    me = db.scalar(select(Faculty).where(Faculty.email == email))
    if me is None:
        me = Faculty(email=email, name=(name or email.split("@")[0]).strip()[:200])
        db.add(me)
        try:
            db.commit()
        except IntegrityError:
            # First sign-in fires several requests at once; another one created the row.
            db.rollback()
            me = db.scalar(select(Faculty).where(Faculty.email == email))
            assert me is not None
            return me
    elif name and me.name != name.strip()[:200]:
        me.name = name.strip()[:200]
        db.commit()
    return me


def is_viewer(person: Faculty) -> bool:
    """Read-only QA/accreditation account (plan 3.12): coverage and syllabi only."""
    return person.email.lower() in {e.lower() for e in get_settings().qa_viewer_emails}


def current_faculty(
    request: Request,
    db: Session = Depends(get_db),
    x_dev_user: str | None = Header(default=None),
    x_dev_name: str | None = Header(default=None),
) -> Faculty:
    me = current_person(request, db, x_dev_user, x_dev_name)
    if is_viewer(me):
        raise HTTPException(403, "This is a read-only QA/accreditation account; it can't open courses, items or exams.")
    return me


def current_viewer(
    request: Request,
    db: Session = Depends(get_db),
    x_dev_user: str | None = Header(default=None),
    x_dev_name: str | None = Header(default=None),
) -> Faculty:
    me = current_person(request, db, x_dev_user, x_dev_name)
    if not is_viewer(me):
        raise HTTPException(403, "QA viewer accounts only.")
    return me


def current_person(request: Request, db: Session, x_dev_user: str | None, x_dev_name: str | None) -> Faculty:
    """Whoever is signed in (faculty or QA viewer)."""
    s = get_settings()
    mode = s.auth_mode
    if mode == "open":
        # Prototype without sign-in: everyone works as one shared demo faculty account.
        return _get_or_create(db, s.open_access_email, s.open_access_name)
    if mode == "dev":
        if not x_dev_user or not _EMAIL.match(x_dev_user.strip()):
            raise HTTPException(401, "Sign in first (dev mode: send X-Dev-User: <email>).")
        return _get_or_create(db, x_dev_user, x_dev_name)
    if mode == "sso":
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            raise HTTPException(401, "Sign in with your university account.")
        try:
            fid = _serializer("session").loads(token, max_age=SESSION_MAX_AGE)["fid"]
        except (BadSignature, KeyError, TypeError) as e:
            raise HTTPException(401, "Your session expired; sign in again.") from e
        me = db.get(Faculty, fid)
        if me is None:
            raise HTTPException(401, "Unknown account; sign in again.")
        return me
    raise HTTPException(500, f"Unknown AUTH_MODE '{mode}'.")


# --------------------------------------------------------------------------- #
# OpenID Connect (plan H.1)
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=4)
def _discovery(issuer: str) -> dict:
    r = httpx.get(issuer.rstrip("/") + "/.well-known/openid-configuration", timeout=10)
    r.raise_for_status()
    return r.json()


_jwks_cache: dict[str, tuple[float, Any]] = {}


def _jwks_client(uri: str) -> jwt.PyJWKClient:
    hit = _jwks_cache.get(uri)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    client = jwt.PyJWKClient(uri)
    _jwks_cache[uri] = (time.time(), client)
    return client


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


@router.get("/config")
def auth_config():
    """Tells the UI which sign-in to show."""
    s = get_settings()
    return {"mode": s.auth_mode, "login_url": "/api/auth/login" if s.auth_mode == "sso" else None,
            "notice": s.notice or None}


@router.get("/login")
def login(next: str = "/"):
    s = get_settings()
    if s.auth_mode != "sso":
        raise HTTPException(404, "SSO is not enabled.")
    meta = _discovery(s.oidc_issuer)
    verifier, challenge = _pkce()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    params = {
        "response_type": "code", "client_id": s.oidc_client_id, "redirect_uri": s.oidc_redirect_uri,
        "scope": "openid email profile", "state": state, "nonce": nonce,
        "code_challenge": challenge, "code_challenge_method": "S256",
    }
    resp = RedirectResponse(meta["authorization_endpoint"] + "?" + urlencode(params), status_code=302)
    flow = _serializer("oidc-flow").dumps({"state": state, "nonce": nonce, "verifier": verifier,
                                            "next": next if next.startswith("/") else "/"})
    resp.set_cookie(FLOW_COOKIE, flow, max_age=600, httponly=True, samesite="lax", secure=s.cookie_secure)
    return resp


@router.get("/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = "",
             db: Session = Depends(get_db)):
    s = get_settings()
    if s.auth_mode != "sso":
        raise HTTPException(404, "SSO is not enabled.")
    if error:
        raise HTTPException(401, f"The university sign-in returned an error: {error}")
    try:
        flow = _serializer("oidc-flow").loads(request.cookies.get(FLOW_COOKIE, ""), max_age=600)
    except BadSignature as e:
        raise HTTPException(400, "Sign-in took too long or came from another browser; try again.") from e
    if not secrets.compare_digest(state, flow["state"]):
        raise HTTPException(400, "Sign-in state mismatch; try again.")
    meta = _discovery(s.oidc_issuer)
    tok = httpx.post(meta["token_endpoint"], data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": s.oidc_redirect_uri,
        "client_id": s.oidc_client_id, "client_secret": s.oidc_client_secret or "", "code_verifier": flow["verifier"],
    }, timeout=15)
    if tok.status_code != 200:
        raise HTTPException(401, "The university sign-in didn't accept the login code.")
    id_token = tok.json().get("id_token")
    if not id_token:
        raise HTTPException(401, "No ID token from the university sign-in.")
    try:
        key = _jwks_client(meta["jwks_uri"]).get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(id_token, key, algorithms=["RS256", "ES256", "PS256"], audience=s.oidc_client_id,
                            issuer=meta.get("issuer", s.oidc_issuer), options={"require": ["exp", "iat", "sub"]})
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"The ID token didn't verify: {e}") from e
    if claims.get("nonce") != flow["nonce"]:
        raise HTTPException(401, "The ID token nonce doesn't match.")
    email = claims.get("email") or claims.get("preferred_username") or claims.get("upn")
    if not email or not _EMAIL.match(email):
        raise HTTPException(401, "The university account has no email address.")
    domains = [d.lower() for d in s.oidc_allowed_domains]
    if domains and email.split("@")[-1].lower() not in domains:
        raise HTTPException(403, "Only university staff accounts can use this tool.")
    me = _get_or_create(db, email, claims.get("name"))
    resp = RedirectResponse(s.frontend_url.rstrip("/") + flow["next"], status_code=302)
    resp.set_cookie(SESSION_COOKIE, _serializer("session").dumps({"fid": me.id}), max_age=SESSION_MAX_AGE,
                    httponly=True, samesite="lax", secure=s.cookie_secure)
    resp.delete_cookie(FLOW_COOKIE)
    from .audit import record

    record(db, me, "login", {"method": "oidc", "issuer": s.oidc_issuer})
    db.commit()
    return resp


@router.post("/logout", status_code=204)
def logout():
    from fastapi.responses import Response

    resp = Response(status_code=204)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@router.get("/whoami")
def whoami(request: Request, db: Session = Depends(get_db), x_dev_user: str | None = Header(default=None),
           x_dev_name: str | None = Header(default=None)):
    me = current_person(request, db, x_dev_user, x_dev_name)
    return {"email": me.email, "name": me.name, "role": "viewer" if is_viewer(me) else "faculty"}
