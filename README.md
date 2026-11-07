# EduForge — AI Teaching Resource & Assessment Support Tool

A faculty-only tool. Faculty upload a vetted AURAK syllabus. The tool extracts a structured course record and flags contradictions. Faculty settle them and lock a working version per course and term. Draft generation (Phase 2) builds on that locked version.

The spec and every decision behind it live in [HANDOFF.md](HANDOFF.md). Decisions D1–D13 are binding.

## Status

**Phase 1 (Course Registry) is built:**

| Part | Where |
|---|---|
| Extraction schema (fixed JSON) | `backend/app/extraction/schema.py` |
| DOCX reader (python-docx; merged cells deduplicated) | `backend/app/extraction/docx_reader.py` |
| PDF reader (pdfplumber; page-split tables stitched, soft wraps rejoined) | `backend/app/extraction/pdf_reader.py` |
| AURAK template mapper (headings, header fields, CLOs, weight table + CLO matrix, weekly plan, appendix programs) | `backend/app/extraction/mapper.py` |
| Normalisers (dates, terms, meeting days, CLO lists, assessment names) | `backend/app/extraction/normalize.py` |
| Validator V1–V13 plus EX (parser problems; V13 grading scale only with grading on) | `backend/app/validation/rules.py` |
| LLM gateway (one interface; `none`/`fake`/`ollama`/OpenAI-compatible; logs model + prompt version) | `backend/app/llm/` |
| Workflow: upload → edit (logged) → settle flags → lock → revise / roll over; coverage report | `backend/app/services/course_versions.py` |
| REST API | `backend/app/api/routes.py` |
| Review and lock UI | `frontend/` |

**The extraction fallback from HANDOFF §8.3 is built** (`backend/app/extraction/llm_fill.py`).

- **When it runs:** only if a core section (CLOs, weight table and matrix, weekly plan, appendix) is still empty after the parser, and a model is configured.
- **What the model gets:** that section's text and, for PDFs, images of its pages. The images handle tables without ruling lines, which the parser can't see.
- **What it must return:** the same fixed schema, put through the same normalisers.
- **Review:** each filled section raises an EX flag that faculty must settle before locking.
- **Failures:** if the model fails or is rate-limited, the section stays empty with a note saying so.

**Phase 2 core is built:** Draft Studio, Faculty Review, Quality Checks and export.

| Part | Where |
|---|---|
| Item schemas: MCQ, short answer, worked problem, practice set, lesson plan, case study, learning resource, rubric | `backend/app/drafts/schemas.py` |
| Versioned prompts, one per type, plus the judge and re-solve prompts | `backend/app/drafts/prompts.py` |
| Generation from the locked version only; regenerate-with-notes | `backend/app/drafts/service.py` |
| Quality checks (see below) | `backend/app/drafts/quality.py` |
| Review: suggested → under_review → approved / rejected | `backend/app/drafts/service.py` |
| Export of approved items only, DOCX/PDF, answer key optional | `backend/app/drafts/export.py` |
| Draft Studio UI | `frontend/src/pages/Drafts.tsx` |

The quality checks are:

- **Rule checks:** schema, the CLO exists, the week is valid, and per-type structure.
- **Skills fit:** questions aimed only at skills-type CLOs get a warning; those CLOs are better served by rubrics or activities.
- **Answer keys recomputed:**
  - numeric answers are recomputed in code with a safe evaluator;
  - MCQs are re-solved independently by the model, without seeing the key.
- **LLM judge:** scores CLO alignment and Bloom fit from 1 to 5.
- **Duplicates:** lexical similarity against the course's other drafts. Switch to embeddings once materials exist.

A failed *required* check blocks approval until the item is edited. A low judge score only warns.

**Since then, following IMPLEMENTATION_PLAN.md (full scope).** `PLAN_STATUS.md` tracks every plan task and each deliberate deviation.

| Phase | Built | Where |
|---|---|---|
| 2 extras | Materials library and grounding; metrics dashboard; LaTeX, diagrams, datasets and charts; code exercises with a sandbox | `app/materials/`, `app/metrics.py`, `app/drafts/rich.py`, `app/drafts/sandbox.py` |
| Hardening | OIDC SSO, audit log, upload guard, WCAG 2.1 AA audit, docs | `app/auth.py`, `app/audit.py`, `app/upload_guard.py`, `docs/` |
| 3 Assessment Builder | Blueprints, parallel forms, usage history, QTI, bank import, term diff, AI-solvability, shared banks, program coverage, QA viewer | `app/builder/`, `frontend/src/pages/Builder.tsx`, `Programs.tsx` |
| 4 Grading Assist | Ships **off** (`GRADING_ENABLED`) until data-protection approval (13.D). Covers: encrypted identities and pseudonyms; anonymisation and an outgoing-prompt guard; V13 and scale confirmation; key, code and rubric suggestions with verified evidence; confirmation grid; feedback approval; Grade Center CSV and PDF release; appeals; calibration harness (`eval/calibration.py`) | `app/grading/`, `frontend/src/pages/Grading.tsx` |
| 5 Blackboard | Ships **off** (`LMS_MODE`) until IT registers the REST application (13.C). Covers: `LmsAdapter` with a Blackboard Learn REST client (3-legged OAuth, refresh, retries, paging); course linking with code and term checks; push of approved forms; pull of submissions into Grading Assist; dry-run, then passback of confirmed grades only. `LMS_MODE=mock` runs it all against a fake Blackboard | `app/lms/`, `frontend/src/pages/Blackboard.tsx` |

## Run it locally (no Docker needed)

```bash
# backend: SQLite by default
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# frontend
cd frontend
npm install
npm run dev          # http://localhost:5173
```

Sign in with any email. Dev mode trusts the `X-Dev-User` header.

**Docker:** `docker compose up --build` gives Postgres+pgvector, the API and the UI.

### LLM provider (D10)

The default is `LLM_PROVIDER=none`. V11 (off-topic text) then uses a keyword heuristic. To use a model:

| Provider | Env vars |
|---|---|
| Local Ollama | `LLM_PROVIDER=ollama LLM_MODEL=llama3.1:8b` |
| Groq free tier | `LLM_PROVIDER=groq LLM_MODEL=<model> LLM_API_KEY=...` |
| OpenRouter | `LLM_PROVIDER=openrouter LLM_MODEL=<model> LLM_API_KEY=...` |
| Gemini | `LLM_PROVIDER=gemini LLM_MODEL=<model> LLM_API_KEY=...` |
| Other OpenAI-compatible | `LLM_PROVIDER=openai_compat LLM_BASE_URL=... LLM_MODEL=...` |

Put these in `backend/.env`, which is git-ignored. The tests ignore it and never call a real model.

Verified on 2026-11-06 with `LLM_PROVIDER=gemini` and `LLM_MODEL=gemini-3.5-flash`. On the key used, `gemini-2.5-flash` returned errors. The gateway retries 429/5xx responses with backoff. If the judge still can't get through, the check is recorded as *skipped* and the draft is kept.

Free API tiers may train on what you send. Send them sample syllabi only, never real exam items, or use Ollama.

## Tests

```bash
cd backend
uv run pytest
```

**`test_acceptance_synthetic.py` is the acceptance seed from HANDOFF §9.** Five synthetic DOCX/PDF syllabi rebuild CSCI 372, CSAI 351, CENG 411, CENG 401 and STAT 100, each with its planted issues. The test checks three things:

- the validator raises every listed issue;
- it raises nothing else that would block locking;
- CSCI 372 comes out clean.

**`test_acceptance_real.py` runs on the real files in `fixtures/syllabi/`** (git-ignored, see the README there). For each file it checks three things:

- the core facts: term, CLO count, PLO count per program, weights summing to 100, and 16 weeks;
- every §9 issue, matched by message;
- that nothing else blocks locking.

As of 2026-11-06, CSCI 372, CSAI 351, CENG 411 and CENG 401 all pass. STAT 100 hasn't been supplied, so its tests skip.

The parser was tuned on these four. The real AURAK files differ from the handoff's description in several ways:

- **Header fields sit inside paragraphs**, e.g. "Course Title: … Course Code: …" on one line.
- **Weight-table cells hold both name and weight**, e.g. "Quizzes 15%".
- **Tables open with merged caption rows.**
- **"Addressed in course" tables don't always follow their own program.**
- **Some PDFs contain no space characters at all.**

## Workflow rules as implemented

- **Flags are never auto-fixed.**
  - When a faculty edit removes the cause, the flag becomes *cleared*.
  - Otherwise faculty *accept it as is*. Accepting an error needs a note.
  - Errors and warnings block locking; info flags don't.
- **Every edit is a JSON-Pointer op on the record, logged with old and new values (D5).** Edits are not routed for approval.
- **A locked version is read-only.**
  - Changing it creates a new version, with settled flags carried over.
  - Roll-over copies it to another term and clears the dates.
- **One locked working version per course and term.**
  - Re-locking your own course replaces your earlier version, which becomes *superseded*.
  - If a different faculty member already locked that course and term, locking is refused. HANDOFF §13.B is still open, so the tool doesn't silently replace someone else's version.
- **Faculty only see their own course versions.**
