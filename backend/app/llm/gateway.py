"""Single LLM gateway (D10, HANDOFF §11).

Every model call in the system goes through ``LLMGateway.json()``:

* the provider is swappable by config (``LLM_PROVIDER``): ``none``, ``fake``,
  ``ollama`` (local open-weight), ``openai_compat`` (Groq, OpenRouter, Gemini's
  OpenAI endpoint, vLLM, LM Studio … anything speaking /chat/completions);
* output is always strict JSON validated against a pydantic schema; one
  repair retry on invalid output, then ``LLMError``;
* each call is reported to ``on_call`` with provider, model, prompt id and
  version, latency and outcome, so the audit log records *which* model and
  prompt produced a result. Prompt text and inputs are not logged, only a hash,
  because question banks count as test material (Honor Code).

Development rule: free API tiers may train on inputs, so send only sample
syllabi there, never real exam items, or use the local Ollama provider.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    """No provider configured; callers should fall back to non-LLM behaviour."""


@dataclass(frozen=True)
class Prompt:
    id: str
    version: str
    system: str
    user: str  # str.format template

    def render(self, **kw) -> str:
        return self.user.format(**kw)


@dataclass
class CallRecord:
    provider: str
    model: str
    prompt_id: str
    prompt_version: str
    input_sha256: str
    latency_ms: int
    ok: bool
    error: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class Provider(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, user: str, schema: dict, images: list[bytes] | None = None) -> str: ...


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #

_RETRY_STATUS = {429, 500, 502, 503, 504}


def post_with_retry(url: str, *, attempts: int = 4, base_delay: float = 2.0, sleep=time.sleep, **kw) -> httpx.Response:
    """POST, retrying rate limits (429), server overload (5xx) and network
    errors with exponential backoff. Honours a numeric Retry-After header
    (capped at 30 s). Free tiers hit 429/503 routinely."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            r = httpx.post(url, **kw)
        except httpx.TransportError as e:
            last = e
        else:
            if r.status_code not in _RETRY_STATUS:
                r.raise_for_status()
                return r
            last = httpx.HTTPStatusError(f"{r.status_code} from {url}", request=r.request, response=r)
            ra = r.headers.get("retry-after", "")
            if i < attempts - 1 and ra.replace(".", "", 1).isdigit():
                sleep(min(float(ra), 30.0))
                continue
        if i < attempts - 1:
            sleep(base_delay * (2 ** i))
    assert last is not None
    raise last


class NullProvider:
    name = "none"
    model = "-"

    def complete_json(self, system: str, user: str, schema: dict, images: list[bytes] | None = None) -> str:
        raise LLMUnavailable("No LLM provider configured (set LLM_PROVIDER).")


class FakeProvider:
    """Deterministic provider for tests: maps prompt id -> response (dict or callable)."""

    name = "fake"

    def __init__(self, responses: dict[str, object] | None = None, model: str = "fake-1") -> None:
        self.responses = responses or {}
        self.model = model
        self.calls: list[tuple[str, str]] = []
        self.images: list[list[bytes]] = []  # images sent with each call
        self._current: str | None = None

    def complete_json(self, system: str, user: str, schema: dict, images: list[bytes] | None = None) -> str:
        self.calls.append((system, user))
        self.images.append(list(images or []))
        resp = self.responses.get(self._current or "")
        if resp is None:
            raise LLMError(f"FakeProvider has no response for prompt '{self._current}'.")
        if callable(resp):
            resp = resp(user)
        return resp if isinstance(resp, str) else json.dumps(resp)


class OllamaProvider:
    name = "ollama"

    def __init__(self, model: str, base_url: str = "http://localhost:11434", timeout: float = 120) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def complete_json(self, system: str, user: str, schema: dict, images: list[bytes] | None = None) -> str:
        user_msg: dict = {"role": "user", "content": user}
        if images:
            user_msg["images"] = [_b64(i) for i in images]  # needs a vision model, e.g. llama3.2-vision
        r = post_with_retry(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "format": schema,  # Ollama structured outputs
                "options": {"temperature": 0},
                "messages": [{"role": "system", "content": system}, user_msg],
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        body = r.json()
        self.last_usage = (body.get("prompt_eval_count"), body.get("eval_count"))
        return body["message"]["content"]


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, model: str, base_url: str, api_key: str | None, timeout: float = 120) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def complete_json(self, system: str, user: str, schema: dict, images: list[bytes] | None = None) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        content: str | list = user
        if images:
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64(i)}"}} for i in images]
        # json_object is the most widely supported mode across free providers;
        # the schema is also given in the system prompt and enforced by pydantic.
        r = post_with_retry(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json={
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system + "\n\nReply with one JSON object matching this JSON Schema:\n"
                     + json.dumps(schema)},
                    {"role": "user", "content": content},
                ],
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        body = r.json()
        usage = body.get("usage") or {}
        self.last_usage = (usage.get("prompt_tokens"), usage.get("completion_tokens"))
        return body["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------- #
# Gateway
# --------------------------------------------------------------------------- #

class LLMGateway:
    def __init__(self, provider: Provider, on_call: Callable[[CallRecord], None] | None = None) -> None:
        self.provider = provider
        self.on_call = on_call

    @property
    def available(self) -> bool:
        return not isinstance(self.provider, NullProvider)

    def json(self, prompt: Prompt, schema: type[T], images: list[bytes] | None = None, **variables) -> T:
        """Call the model and return validated JSON. ``images`` (PNG bytes) are
        sent alongside the text for vision-capable models."""
        user = prompt.render(**variables)
        js = schema.model_json_schema()
        h = hashlib.sha256((prompt.system + "\n" + user).encode())
        for img in images or []:
            h.update(img)
        digest = h.hexdigest()
        if isinstance(self.provider, FakeProvider):
            self.provider._current = prompt.id
        last_err: Exception | None = None
        for attempt in range(2):
            _throttle(self.provider)
            t0 = time.perf_counter()
            msg = user if attempt == 0 else (
                user + f"\n\nYour previous reply was not valid ({last_err}). Reply with valid JSON only.")
            try:
                raw = self.provider.complete_json(prompt.system, msg, js, images=images)
                result = schema.model_validate_json(_strip_fences(raw))
                self._log(prompt, digest, t0, ok=True)
                return result
            except LLMUnavailable:
                raise
            except (ValidationError, ValueError) as e:
                last_err = e
                self._log(prompt, digest, t0, ok=False, error=f"invalid output: {e}"[:500])
            except (httpx.HTTPError, KeyError, LLMError) as e:
                self._log(prompt, digest, t0, ok=False, error=str(e)[:500])
                raise LLMError(str(e)) from e
        raise LLMError(f"Model output failed schema validation twice: {last_err}")

    def _log(self, prompt: Prompt, digest: str, t0: float, ok: bool, error: str | None = None) -> None:
        if self.on_call:
            pt, ct = getattr(self.provider, "last_usage", None) or (None, None)
            self.on_call(CallRecord(
                provider=self.provider.name, model=self.provider.model,
                prompt_id=prompt.id, prompt_version=prompt.version, input_sha256=digest,
                latency_ms=int((time.perf_counter() - t0) * 1000), ok=ok, error=error,
                prompt_tokens=pt if ok else None, completion_tokens=ct if ok else None,
            ))


_rate_lock = threading.Lock()
_next_slot: dict[str, float] = {}


def _throttle(provider: Provider) -> None:
    """Client-side rate limit (plan 0.5a): at most LLM_MAX_RPM calls per minute
    per provider+model in this process, spaced evenly. Free tiers allow about
    5-15 requests a minute; staying under that avoids most 429s."""
    if isinstance(provider, (FakeProvider, NullProvider)):
        return
    from app.config import get_settings

    rpm = get_settings().llm_max_rpm
    if rpm <= 0:
        return
    key = f"{provider.name}:{provider.model}"
    gap = 60.0 / rpm
    with _rate_lock:
        now = time.monotonic()
        slot = max(now, _next_slot.get(key, 0.0))
        _next_slot[key] = slot + gap
    if slot > now:
        time.sleep(slot - now)


def _strip_fences(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    return s.strip()


def build_provider(provider: str, model: str | None, base_url: str | None, api_key: str | None) -> Provider:
    p = (provider or "none").lower()
    if p == "none":
        return NullProvider()
    if p == "fake":
        return FakeProvider()
    if p == "ollama":
        return OllamaProvider(model=model or "llama3.1:8b", base_url=base_url or "http://localhost:11434")
    if p in {"openai_compat", "openai", "groq", "openrouter", "gemini"}:
        defaults = {
            "groq": "https://api.groq.com/openai/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
        }
        url = base_url or defaults.get(p)
        if not url or not model:
            raise ValueError(f"LLM provider '{p}' needs LLM_MODEL and LLM_BASE_URL.")
        return OpenAICompatProvider(model=model, base_url=url, api_key=api_key)
    raise ValueError(f"Unknown LLM provider '{provider}'.")
