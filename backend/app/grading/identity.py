"""Student identities and anonymisation (plan 4.1, 4.3).

* Identities are Fernet-encrypted at rest with IDENTITY_KEY. Each student has a
  random pseudonym, and everything else in Phase 4 uses it.
* ``scrub`` removes identities from answer text at intake: names, IDs and emails
  from the section roster, plus pattern rules (emails, phone numbers, long digit
  IDs, "Name: …" lines, "my name is …"). Originals are not stored.
* ``leaks`` is the second line of defence, run on every prompt before a model
  call: it compares keyed hashes of the prompt's tokens with the roster's
  identity hashes, so no identity has to be decrypted to check.

Name parts are matched only when capitalised (or in a script without case),
so an answer saying "will" is untouched when a student is called Will.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings
from app.services.course_versions import WorkflowError

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w.])\+?\d[\d \-()]{7,}\d(?![\w.])")
LONG_ID = re.compile(r"(?<![\w.,])[A-Za-z]{0,3}\d{7,}(?![\w.,]\d)")
LABELLED = re.compile(r"(?im)^([ \t]*(?:(?:student|full)[ \t]+)?(?:name|student[ \t]*id|id[ \t]*(?:no\.?|number)|"
                      r"e-?mail|submitted[ \t]+by|prepared[ \t]+by)[ \t]*[:\-][ \t]*)(\S.*)$")
MY_NAME = re.compile(r"(?i)\b(my name is|i am called|this is)\s+([A-ZÀ-ɏ؀-ۿ][\w'\-]*"
                     r"(?:\s+[A-ZÀ-ɏ؀-ۿ][\w'\-]*){0,3})")
_WORD = re.compile(r"[^\W\d_][\w'\-]*", re.UNICODE)
_IDISH = re.compile(r"[A-Za-z]{0,3}\d[\w\-]*")


@dataclass
class Person:
    external_id: str
    name: str | None = None
    email: str | None = None


# ---- keys -----------------------------------------------------------------
def _key() -> str:
    key = get_settings().identity_key
    if not key:
        raise WorkflowError("IDENTITY_KEY is not set, so student identities can't be stored. See docs/ops-runbook.md.", 500)
    return key


def _fernet() -> Fernet:
    try:
        return Fernet(_key().encode())
    except ValueError as e:
        raise WorkflowError("IDENTITY_KEY is not a valid Fernet key.", 500) from e


def encrypt(s: str | None) -> str | None:
    return None if s is None else _fernet().encrypt(s.encode()).decode()


def decrypt(s: str | None) -> str | None:
    if s is None:
        return None
    try:
        return _fernet().decrypt(s.encode()).decode()
    except InvalidToken as e:
        raise WorkflowError("A stored identity can't be decrypted: IDENTITY_KEY changed?", 500) from e


def mac(kind: str, token: str) -> str:
    k = hashlib.sha256(b"eduforge-identity-mac:" + _key().encode()).digest()
    return kind + ":" + hmac.new(k, token.strip().lower().encode(), hashlib.sha256).hexdigest()[:32]


def norm_id(x: str) -> str:
    return re.sub(r"\s+", "", x).lower()


def new_pseudonym() -> str:
    return "S-" + "".join(secrets.choice(_ALPHABET) for _ in range(6))


def name_parts(name: str | None) -> list[str]:
    return [p for p in _WORD.findall(name or "") if len(p) >= 2]


def token_macs(p: Person) -> list[str]:
    out = {mac("id", norm_id(p.external_id))}
    if p.email:
        out |= {mac("em", p.email), mac("em", p.email.split("@")[0])}
    out |= {mac("nm", part) for part in name_parts(p.name)}
    return sorted(out)


# ---- anonymisation (4.3) ----------------------------------------------------
def _name_like(word: str) -> bool:
    c = word[0]
    return c.isupper() or not c.isascii()  # capitalised, or a script without case (Arabic)


def scrub(text: str, roster: list[Person]) -> tuple[str, int]:
    """Remove identities; returns (clean text, number of redactions)."""
    t = text or ""
    t = LABELLED.sub(lambda m: m.group(1) + "[REDACTED]", t)
    t = EMAIL.sub("[EMAIL]", t)
    t = MY_NAME.sub(lambda m: m.group(1) + " [NAME]", t)
    for p in roster:
        if p.name and len(p.name.strip()) >= 3:
            full = r"\s+".join(map(re.escape, p.name.split()))
            t = re.sub(r"(?i)(?<!\w)" + full + r"(?!\w)", "[NAME]", t)
        if p.external_id.strip():
            t = re.sub(r"(?i)(?<!\w)" + re.escape(p.external_id.strip()) + r"(?!\w)", "[ID]", t)
        if p.email:
            t = re.sub(r"(?i)(?<![\w.])" + re.escape(p.email.split("@")[0]) + r"(?!\w)", "[EMAIL]", t)
    parts = {part.lower() for p in roster for part in name_parts(p.name)}
    if parts:
        t = _WORD.sub(lambda m: "[NAME]" if m.group(0).lower() in parts and _name_like(m.group(0)) else m.group(0), t)
    t = PHONE.sub("[PHONE]", t)
    t = LONG_ID.sub("[ID]", t)
    return t, _count(text or "", t)


def _count(before: str, after: str) -> int:
    tags = ("[NAME]", "[ID]", "[EMAIL]", "[PHONE]", "[REDACTED]")
    return sum(after.count(x) - before.count(x) for x in tags)


def leaks(text: str, macs: set[str], patterns: bool = False) -> list[str]:
    """Identity kinds found in text bound for a model (empty = clean). ``patterns``
    also rejects ID- or phone-like numbers: use it on student text only, since
    item text may legitimately hold long numbers."""
    found: set[str] = set()
    for e in EMAIL.findall(text):
        if mac("em", e) in macs or mac("em", e.split("@")[0]) in macs:
            found.add("email")
    for w in _WORD.findall(text):
        if _name_like(w) and mac("nm", w) in macs:
            found.add("name")
        if mac("em", w) in macs:
            found.add("email")
    for tok in _IDISH.findall(text):
        if mac("id", norm_id(tok)) in macs:
            found.add("student id")
    if patterns and (LONG_ID.search(text) or PHONE.search(text) or EMAIL.search(text)):
        found.add("number that looks like an ID or phone")
    return sorted(found)
