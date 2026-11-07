import httpx
import pytest

from app.llm import gateway
from app.llm.gateway import post_with_retry


def _resp(status, headers=None):
    return httpx.Response(status, headers=headers or {}, json={"ok": status == 200},
                          request=httpx.Request("POST", "https://x"))


def test_retries_overload_then_succeeds(monkeypatch):
    seq = iter([_resp(503), _resp(429, {"retry-after": "1"}), _resp(200)])
    monkeypatch.setattr(gateway.httpx, "post", lambda url, **kw: next(seq))
    waits = []
    r = post_with_retry("https://x", sleep=waits.append)
    assert r.status_code == 200 and waits == [2.0, 1.0]


def test_gives_up_after_attempts(monkeypatch):
    monkeypatch.setattr(gateway.httpx, "post", lambda url, **kw: _resp(503))
    with pytest.raises(httpx.HTTPStatusError):
        post_with_retry("https://x", attempts=3, sleep=lambda s: None)


def test_client_errors_are_not_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(gateway.httpx, "post", lambda url, **kw: calls.append(1) or _resp(400))
    with pytest.raises(httpx.HTTPStatusError):
        post_with_retry("https://x", sleep=lambda s: None)
    assert len(calls) == 1


def test_v11_fallback_says_why_when_model_fails():
    from app.extraction.pipeline import extract
    from app.llm.gateway import FakeProvider, LLMGateway
    from app.validation.rules import v11_on_topic
    from tests.test_acceptance_synthetic import _file

    rec = extract(*_file("CENG401"))
    failing = LLMGateway(FakeProvider({}))  # no canned answer -> LLMError
    flags = v11_on_topic(rec, failing)
    assert flags and "model call failed" in flags[0].message and "no LLM configured" not in flags[0].message
    assert "no LLM configured" in v11_on_topic(rec, None)[0].message


class _Echo:
    """A non-fake provider (so throttling applies) that reports token usage."""

    name = "echo"
    model = "echo-1"

    def complete_json(self, system, user, schema, images=None):
        self.last_usage = (120, 30)
        return '{"answer": "ok"}'


def test_gateway_logs_tokens_and_throttles(monkeypatch):
    import time

    from pydantic import BaseModel

    from app.config import get_settings
    from app.llm.gateway import LLMGateway, Prompt

    class Out(BaseModel):
        answer: str

    monkeypatch.setattr(get_settings(), "llm_max_rpm", 1200)  # one call per 0.05 s
    records = []
    gw = LLMGateway(_Echo(), on_call=records.append)
    p = Prompt(id="t", version="1", system="s", user="u")
    t0 = time.monotonic()
    for _ in range(4):
        assert gw.json(p, Out).answer == "ok"
    # 3 gaps of 0.05 s. The bound is loose because sleep() can return a
    # fraction early and a loaded machine shaves the measurement; without
    # throttling this loop takes about 0 s, so 0.1 still proves it ran.
    assert time.monotonic() - t0 >= 0.1
    assert [(r.prompt_tokens, r.completion_tokens) for r in records] == [(120, 30)] * 4
