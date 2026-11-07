"""LLM fallback for sections the parser can't read (HANDOFF §8.3)."""

from __future__ import annotations

from app.extraction.pipeline import extract
from app.llm.gateway import FakeProvider, LLMGateway
from app.validation.rules import validate
from tests.synth.render import to_docx, to_pdf
from tests.synth.specs import CSAI351, STAT100, build

PNG = b"\x89PNG\r\n\x1a\n"


def _gridless_stat100() -> bytes:
    return to_pdf(build({**STAT100, "weekly_gridless": True}))


def _weeks_answer(user: str) -> dict:
    # What a model would transcribe from STAT 100's weekly table.
    rows = STAT100["weekly_tables"][0]
    return {"weeks": [{"week_no": int(r[0]), "topics": [t.strip() for t in r[1].split(";")],
                       "readings": [r[2]] if r[2] else [], "assessment_text": r[3], "clo_text": r[4]} for r in rows]}


def test_gridless_table_is_not_parsed_without_a_model():
    rec = extract("stat.pdf", _gridless_stat100())
    assert rec.weekly == []
    assert any(f.rule_id == "V12" and "Weekly" in f.message for f in validate(rec))


def test_model_fills_gridless_weekly_table_from_text_and_page_images():
    fake = FakeProvider({"extract.weekly": _weeks_answer})
    rec = extract("stat.pdf", _gridless_stat100(), llm=LLMGateway(fake))

    assert [w.week_no for w in rec.weekly] == list(range(1, 17))
    w5 = next(w for w in rec.weekly if w.week_no == 5)
    assert [a.name for a in w5.assessments] == ["Quiz 1"] and w5.clo_numbers == [1, 2]
    assert str(w5.assessments[0].due_date) == "2026-09-23"  # same normalisers as the parser

    # Only the missing section was asked for; the model saw the section text and page images.
    assert len(fake.calls) == 1
    _, user = fake.calls[0]
    assert "Counting techniques" in user
    assert fake.images[0] and all(img.startswith(PNG) for img in fake.images[0])

    # The filled section is flagged for faculty review, and the §9 checks still work on it.
    flags = validate(rec)
    assert any(f.rule_id == "EX" and "extract.weekly@1" in f.message for f in flags)
    assert any(f.rule_id == "V9" and "Quiz 1" in f.message for f in flags)


def test_model_failure_leaves_section_empty_with_a_note():
    rec = extract("stat.pdf", _gridless_stat100(), llm=LLMGateway(FakeProvider({})))
    assert rec.weekly == []
    assert any("model fallback failed" in n.message for n in rec.notes)


def test_retries_without_images_when_model_rejects_them():
    calls = {"n": 0}

    def answer(user):
        calls["n"] += 1
        if calls["n"] == 1:
            return "this model can't read images"  # invalid JSON -> retried once, then LLMError
        if calls["n"] == 2:
            return "still no"
        return _weeks_answer(user)

    fake = FakeProvider({"extract.weekly": answer})
    rec = extract("stat.pdf", _gridless_stat100(), llm=LLMGateway(fake))
    assert len(rec.weekly) == 16
    assert fake.images[-1] == []  # the successful call was text-only
    assert any("from its text." in n.message for n in rec.notes)


def test_parsed_sections_are_never_sent_or_overwritten():
    fake = FakeProvider({})
    rec = extract("csai.docx", to_docx(build(CSAI351)), llm=LLMGateway(fake))
    assert fake.calls == []  # nothing was missing
    assert len(rec.weekly) == 16 and len(rec.clos) == 3


def test_rate_limit_is_not_retried_text_only():
    from app.llm.gateway import LLMError

    class RateLimited(FakeProvider):
        def complete_json(self, system, user, schema, images=None):
            self.calls.append((system, user))
            raise LLMError("429 from https://example")

    fake = RateLimited({})
    rec = extract("stat.pdf", _gridless_stat100(), llm=LLMGateway(fake))
    assert rec.weekly == [] and len(fake.calls) == 1
