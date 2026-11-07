"""Blackboard Learn REST adapter (plan 5.1, 5.6).

* OAuth 2 authorization-code flow (3-legged), so every call acts as the faculty
  member; tokens refresh on expiry or a 401.
* Retries with backoff on 429/5xx, honouring Retry-After; a minimum interval
  between calls (rate limit); paging followed via ``paging.nextPage``.
* Every request is appended to a CallLog for the sync record.

Endpoints are the public Learn REST API (/learn/api/public/v1|v2/...).
There is no public REST endpoint to import a question pool, so pushing a form
creates its Grade Center column and the QTI package is imported by hand
(plan 5.3 "or via QTI upload where the REST API lacks it").
"""

from __future__ import annotations

import time
from collections.abc import Callable
from urllib.parse import urlencode

import httpx

from .adapter import CallLog, LmsAttempt, LmsColumn, LmsCourse, LmsError, LmsGrade, LmsUser, Token

V1 = "/learn/api/public/v1"
V2 = "/learn/api/public/v2"


class BlackboardAdapter:
    name = "blackboard"

    def __init__(self, base_url: str, app_key: str, app_secret: str, redirect_uri: str,
                 client: httpx.Client | None = None, log: CallLog | None = None, retries: int = 4,
                 min_interval: float = 0.05, sleep: Callable[[float], None] = time.sleep,
                 on_refresh: Callable[[Token], None] | None = None) -> None:
        self.base = base_url.rstrip("/")
        self.key, self.secret, self.redirect_uri = app_key, app_secret, redirect_uri
        self.http = client or httpx.Client(timeout=30)
        self.log = log or CallLog()
        self.retries, self.min_interval, self.sleep = retries, min_interval, sleep
        self.on_refresh = on_refresh
        self._last = 0.0

    # ---- OAuth (5.1) ----------------------------------------------------------
    def authorize_url(self, state: str) -> str:
        q = {"redirect_uri": self.redirect_uri, "response_type": "code", "client_id": self.key,
             "scope": "read write offline", "state": state}
        return f"{self.base}{V1}/oauth2/authorizationcode?{urlencode(q)}"

    def _token(self, data: dict) -> Token:
        r = self._send("POST", f"{V1}/oauth2/token", data=data, auth=(self.key, self.secret), authed=None)
        js = r.json()
        return Token(js["access_token"], js.get("refresh_token"), time.time() + float(js.get("expires_in", 3600)) - 30,
                     str(js.get("user_id", "")))

    def exchange_code(self, code: str) -> Token:
        return self._token({"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri})

    def refresh(self, token: Token) -> Token:
        if not token.refresh_token:
            raise LmsError("The Blackboard sign-in expired; connect your account again.", 401)
        new = self._token({"grant_type": "refresh_token", "refresh_token": token.refresh_token})
        new.user_id = new.user_id or token.user_id
        new.refresh_token = new.refresh_token or token.refresh_token
        if self.on_refresh:
            self.on_refresh(new)
        return new

    # ---- transport with retries (5.6) -------------------------------------------
    def _send(self, method: str, path: str, authed: Token | None, **kw) -> httpx.Response:
        url = path if path.startswith("http") else self.base + path
        refreshed = False
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                self.sleep(wait)
            headers = dict(kw.pop("headers", {}) or {})
            if authed is not None:
                if authed.expires_at < time.time() and not refreshed:
                    fresh = self.refresh(authed)
                    authed.__dict__.update(fresh.__dict__)
                    refreshed = True
                headers["Authorization"] = f"Bearer {authed.access_token}"
            try:
                r = self.http.request(method, url, headers=headers, **kw)
            except httpx.TransportError as e:
                self.log.add(method, path, 0, f"network error: {e}")
                if attempt == self.retries:
                    raise LmsError(f"Blackboard didn't answer ({e}).", 503) from e
                self.sleep(min(2 ** attempt, 30))
                continue
            finally:
                self._last = time.monotonic()
            self.log.add(method, path.split("?")[0], r.status_code)
            if r.status_code == 401 and authed is not None and not refreshed:
                fresh = self.refresh(authed)
                authed.__dict__.update(fresh.__dict__)
                refreshed = True
                continue
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == self.retries:
                    raise LmsError(f"Blackboard is busy or failing ({r.status_code}); try again later.", 503)
                ra = r.headers.get("Retry-After")
                self.sleep(min(float(ra) if ra and ra.replace(".", "").isdigit() else 2 ** attempt, 60))
                continue
            if r.status_code >= 400:
                msg = ""
                try:
                    msg = r.json().get("message", "")
                except ValueError:
                    pass
                raise LmsError(f"Blackboard refused {method} {path.split('?')[0]} ({r.status_code}) {msg}".strip(),
                               r.status_code if r.status_code in {403, 404, 409} else 502)
            return r
        raise LmsError("Blackboard request failed.", 503)  # pragma: no cover

    def _all(self, token: Token, path: str) -> list[dict]:
        out: list[dict] = []
        nxt: str | None = path
        while nxt:
            js = self._send("GET", nxt, token).json()
            out += js.get("results", [])
            nxt = (js.get("paging") or {}).get("nextPage")
        return out

    # ---- data -------------------------------------------------------------------------
    def courses(self, token: Token) -> list[LmsCourse]:
        rows = self._all(token, f"{V1}/users/{token.user_id}/courses?expand=course&fields=course,courseRoleId")
        out, terms = [], {}
        for m in rows:
            c = m.get("course") or {}
            if m.get("courseRoleId", "Instructor") not in {"Instructor", "TeachingAssistant", "CourseBuilder"}:
                continue
            tid = c.get("termId")
            if tid and tid not in terms:
                try:
                    terms[tid] = self._send("GET", f"{V1}/terms/{tid}", token).json().get("name")
                except LmsError:
                    terms[tid] = None
            out.append(LmsCourse(c["id"], c.get("courseId", ""), c.get("name", ""), terms.get(tid) if tid else None))
        return out

    def columns(self, token: Token, course: str) -> list[LmsColumn]:
        return [LmsColumn(c["id"], c.get("name", ""), (c.get("score") or {}).get("possible"))
                for c in self._all(token, f"{V2}/courses/{course}/gradebook/columns")]

    def create_column(self, token: Token, course: str, name: str, possible: float, description: str) -> LmsColumn:
        body = {"name": name, "description": description, "score": {"possible": possible},
                "availability": {"available": "No"}, "grading": {"type": "Manual", "scoringModel": "Last"}}
        c = self._send("POST", f"{V2}/courses/{course}/gradebook/columns", token, json=body).json()
        return LmsColumn(c["id"], c.get("name", name), possible)

    def grades(self, token: Token, course: str, column: str) -> list[LmsGrade]:
        return [LmsGrade(g["userId"], g.get("score"), g.get("feedback"))
                for g in self._all(token, f"{V2}/courses/{course}/gradebook/columns/{column}/users")]

    def put_grade(self, token: Token, course: str, column: str, user: str, score: float, feedback: str | None) -> None:
        body: dict = {"score": score}
        if feedback:
            body["feedback"] = feedback
        self._send("PATCH", f"{V2}/courses/{course}/gradebook/columns/{column}/users/{user}", token, json=body)

    def attempts(self, token: Token, course: str, column: str) -> list[LmsAttempt]:
        return [LmsAttempt(a["id"], a["userId"], a.get("text") or "", a.get("status", ""))
                for a in self._all(token, f"{V2}/courses/{course}/gradebook/columns/{column}/attempts")]

    def user(self, token: Token, user: str) -> LmsUser:
        u = self._send("GET", f"{V1}/users/{user}", token).json()
        nm = u.get("name") or {}
        return LmsUser(u["id"], u.get("userName", ""), u.get("studentId"),
                       " ".join(x for x in (nm.get("given"), nm.get("family")) if x) or None,
                       (u.get("contact") or {}).get("email"))

    def roster(self, token: Token, course: str) -> list[LmsUser]:
        rows = self._all(token, f"{V1}/courses/{course}/users?expand=user")
        out = []
        for m in rows:
            if m.get("courseRoleId") != "Student":
                continue
            u = m.get("user") or {}
            nm = u.get("name") or {}
            out.append(LmsUser(m["userId"], u.get("userName", ""), u.get("studentId"),
                               " ".join(x for x in (nm.get("given"), nm.get("family")) if x) or None,
                               (u.get("contact") or {}).get("email")))
        return out
