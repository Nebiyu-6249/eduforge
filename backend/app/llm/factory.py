from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import LLMCall

from .gateway import CallRecord, LLMGateway, Provider, build_provider

_provider_override: Provider | None = None


def set_provider_override(p: Provider | None) -> None:
    """Tests: force a provider (e.g. FakeProvider) regardless of settings."""
    global _provider_override
    _provider_override = p


def get_gateway(db: Session | None = None, faculty_id: int | None = None,
                course_version_id: int | None = None) -> LLMGateway:
    s = get_settings()
    provider = _provider_override or build_provider(s.llm_provider, s.llm_model, s.llm_base_url, s.llm_api_key)

    def log(rec: CallRecord) -> None:
        if db is None:
            return
        db.add(LLMCall(provider=rec.provider, model=rec.model, prompt_id=rec.prompt_id,
                       prompt_version=rec.prompt_version, input_sha256=rec.input_sha256,
                       latency_ms=rec.latency_ms, ok=rec.ok, error=rec.error,
                       prompt_tokens=rec.prompt_tokens, completion_tokens=rec.completion_tokens,
                       faculty_id=faculty_id, course_version_id=course_version_id))

    return LLMGateway(provider, on_call=log)
