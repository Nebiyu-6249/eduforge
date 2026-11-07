"""An in-memory Blackboard Learn REST server, served through httpx.MockTransport.

The real BlackboardAdapter runs against it unchanged, so tests and LMS_MODE=mock
exercise the same code that will talk to the university's sandbox (13.C).
It implements only what the adapter uses, with Blackboard's shapes: paged
``{"results", "paging": {"nextPage"}}`` lists, OAuth codes/tokens/refresh, grade
columns, grades, attempts, users and memberships.

Chaos controls (plan 5.6): ``fail_next`` (status codes for the next requests,
e.g. [429, 503]), ``expire_tokens()``, ``broken_users`` (PATCH always fails).
"""

from __future__ import annotations

import itertools
import json
import re
import secrets
from urllib.parse import parse_qs

import httpx

BASE = "https://blackboard.mock"
PAGE = 2  # small pages, so paging is always exercised


class FakeBlackboard:
    def __init__(self) -> None:
        self.users: dict[str, dict] = {}
        self.terms: dict[str, dict] = {}
        self.courses: dict[str, dict] = {}
        self.members: dict[str, list[tuple[str, str]]] = {}
        self.columns: dict[str, dict[str, dict]] = {}
        self.grades: dict[tuple[str, str], dict[str, dict]] = {}
        self.attempts: dict[tuple[str, str], list[dict]] = {}
        self.codes: dict[str, str] = {}
        self.tokens: dict[str, str] = {}
        self.refresh_tokens: dict[str, str] = {}
        self.fail_next: list[int] = []
        self.broken_users: set[str] = set()
        self.requests: list[tuple[str, str]] = []
        self._ids = itertools.count(100)
        self.auto_attempts: list[tuple[str, str]] = []  # (user_id, text) submitted to every new column (mock mode)

    # ---- seeding ----------------------------------------------------------------
    def _id(self, kind: str) -> str:
        return f"_{next(self._ids)}_{kind}"

    def add_user(self, user_name: str, name: str, student_id: str | None = None, email: str | None = None) -> str:
        uid = self._id("1")
        given, _, family = name.partition(" ")
        self.users[uid] = {"id": uid, "userName": user_name, "studentId": student_id,
                           "name": {"given": given, "family": family}, "contact": {"email": email}}
        return uid

    def add_term(self, name: str) -> str:
        tid = self._id("t")
        self.terms[tid] = {"id": tid, "name": name}
        return tid

    def add_course(self, course_id: str, name: str, term_id: str | None, instructor: str, students: list[str]) -> str:
        cid = self._id("c")
        self.courses[cid] = {"id": cid, "courseId": course_id, "name": name, "termId": term_id}
        self.members[cid] = [(instructor, "Instructor")] + [(s, "Student") for s in students]
        self.columns[cid] = {}
        return cid

    def authorize(self, user_id: str) -> str:
        """What the browser round-trip would produce: an authorization code for this user."""
        code = secrets.token_urlsafe(8)
        self.codes[code] = user_id
        return code

    def expire_tokens(self) -> None:
        self.tokens.clear()

    def add_attempt(self, course: str, column: str, user: str, text: str) -> None:
        self.attempts.setdefault((course, column), []).append(
            {"id": self._id("a"), "userId": user, "text": text, "status": "NeedsGrading"})

    # ---- transport ------------------------------------------------------------------
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=self.transport(), base_url=BASE)

    def _page(self, req: httpx.Request, rows: list[dict]) -> httpx.Response:
        q = parse_qs(req.url.query.decode())
        off = int(q.get("offset", ["0"])[0])
        body: dict = {"results": rows[off:off + PAGE]}
        if off + PAGE < len(rows):
            rest = {k: v[0] for k, v in q.items() if k != "offset"}
            extra = "&".join(f"{k}={v}" for k, v in rest.items())
            body["paging"] = {"nextPage": f"{req.url.path}?offset={off + PAGE}" + (f"&{extra}" if extra else "")}
        return httpx.Response(200, json=body)

    def handle(self, req: httpx.Request) -> httpx.Response:
        path, method = req.url.path, req.method
        self.requests.append((method, path))
        if self.fail_next:
            code = self.fail_next.pop(0)
            return httpx.Response(code, headers={"Retry-After": "0"} if code == 429 else {}, json={"message": "chaos"})
        if path.endswith("/oauth2/token"):
            form = parse_qs(req.content.decode())
            grant = form.get("grant_type", [""])[0]
            if grant == "authorization_code":
                uid = self.codes.pop(form.get("code", [""])[0], None)
            else:
                uid = self.refresh_tokens.get(form.get("refresh_token", [""])[0])
            if uid is None:
                return httpx.Response(400, json={"message": "invalid_grant"})
            access, refresh = secrets.token_urlsafe(12), secrets.token_urlsafe(12)
            self.tokens[access] = uid
            self.refresh_tokens[refresh] = uid
            return httpx.Response(200, json={"access_token": access, "token_type": "bearer", "expires_in": 3600,
                                             "refresh_token": refresh, "scope": "read write offline", "user_id": uid})
        me = self.tokens.get(req.headers.get("Authorization", "").removeprefix("Bearer "))
        if me is None:
            return httpx.Response(401, json={"message": "Bearer token is invalid"})

        if m := re.fullmatch(r"/learn/api/public/v1/users/([^/]+)/courses", path):
            rows = [{"courseId": cid, "courseRoleId": role, "course": self.courses[cid]}
                    for cid, ms in self.members.items() for u, role in ms if u == m.group(1)]
            return self._page(req, rows)
        if m := re.fullmatch(r"/learn/api/public/v1/terms/([^/]+)", path):
            return httpx.Response(200, json=self.terms[m.group(1)]) if m.group(1) in self.terms else httpx.Response(404, json={})
        if m := re.fullmatch(r"/learn/api/public/v1/users/([^/]+)", path):
            u = self.users.get(m.group(1))
            return httpx.Response(200, json=u) if u else httpx.Response(404, json={"message": "no user"})
        if m := re.fullmatch(r"/learn/api/public/v1/courses/([^/]+)/users", path):
            rows = [{"userId": u, "courseRoleId": role, "user": self.users[u]} for u, role in self.members.get(m.group(1), [])]
            return self._page(req, rows)

        m = re.fullmatch(r"/learn/api/public/v2/courses/([^/]+)/gradebook/columns(?:/([^/]+))?(?:/(users|attempts))?(?:/([^/]+))?", path)
        if not m:
            return httpx.Response(404, json={"message": f"no route {path}"})
        course, col, sub, user = m.groups()
        if course not in self.courses or not any(u == me and r == "Instructor" for u, r in self.members[course]):
            return httpx.Response(403, json={"message": "not an instructor of this course"})
        cols = self.columns[course]
        if col is None:
            if method == "POST":
                body = json.loads(req.content)
                cid = self._id("col")
                cols[cid] = {"id": cid, "name": body["name"], "score": body.get("score", {}),
                             "description": body.get("description", "")}
                for uid, text in self.auto_attempts:
                    self.add_attempt(course, cid, uid, text)
                return httpx.Response(201, json=cols[cid])
            return self._page(req, list(cols.values()))
        if col not in cols:
            return httpx.Response(404, json={"message": "no column"})
        if sub == "attempts":
            return self._page(req, self.attempts.get((course, col), []))
        if sub == "users" and user is None:
            g = self.grades.get((course, col), {})
            return self._page(req, [{"userId": u, "columnId": col, **v} for u, v in g.items()])
        if sub == "users" and method == "PATCH":
            if user in self.broken_users:
                return httpx.Response(500, json={"message": "internal error"})
            if not any(u == user and r == "Student" for u, r in self.members[course]):
                return httpx.Response(404, json={"message": "user not enrolled"})
            body = json.loads(req.content)
            self.grades.setdefault((course, col), {})[user] = {"score": body.get("score"), "feedback": body.get("feedback")}
            return httpx.Response(200, json={"userId": user, **self.grades[(course, col)][user]})
        return httpx.Response(405, json={"message": "unsupported"})


_shared: FakeBlackboard | None = None


def shared() -> FakeBlackboard:
    """The process-wide fake used by LMS_MODE=mock."""
    global _shared
    if _shared is None:
        _shared = FakeBlackboard()
    return _shared
