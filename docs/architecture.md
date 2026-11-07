# EduForge: architecture

This is for developers joining the project. Read it together with IMPLEMENTATION_PLAN.md (the spec) and PLAN_STATUS.md (where each task stands).

```
React UI (frontend/) ──HTTP──► FastAPI (backend/app) ──► Postgres + pgvector
                                   │   ├─ jobs table ◄── worker (python -m app.worker)
                                   │   └─ file storage (uploads, page images)
                                   └─► LLM gateway (one interface; Ollama / Gemini / Groq / OpenRouter / fake)
```

## Backend modules

| Path | What it does |
|---|---|
| `extraction/` | Syllabus → `ExtractedSyllabus`. The `docx_reader` and `pdf_reader` produce blocks. The `mapper` applies the AURAK template and records a source location for every value. `normalize` handles dates, terms, days and CLO lists. `llm_fill` is the model fallback for sections the parser can't read (text plus page images). |
| `validation/` | Rules V1–V13 plus EX. They only flag, never fix. Some flags offer "choose a value" fixes. V13 (grading scale) runs only when grading is on. |
| `builder/` | Phase 3 Assessment Builder: blueprint, assembly, parallel versions, QTI, bank import, term diff, solvability, program coverage |
| `grading/` | Phase 4 Grading Assist, off unless `GRADING_ENABLED`. `identity` handles encryption, pseudonyms, the anonymiser and the outgoing-prompt guard. `intake` reads rosters, CSV and file submissions. `scoring` does key, code (Docker only) and rubric suggestions with verified evidence. `service` covers the workflow, confirmation rules, appeals, the scale and calibration sets. `release` writes the Grade Center CSV and feedback PDFs. `calibration` holds the agreement metrics. |
| `services/course_versions.py` | Gate 1: edits as logged JSON-Pointer patches, flag reconciliation, lock, revise, roll-over, carry-over, coverage. |
| `materials/` | Course materials library: extract → chunk → embed → retrieve, with the licence guard and the exam-hygiene rule. |
| `drafts/` | Draft Studio: schemas per item type, versioned prompts, generation with grounding, quality checks, review (gate 2), export. `rich.py` covers math, diagrams, datasets and charts; `sandbox.py` runs code. |
| `lms/` | Phase 5, off unless `LMS_MODE`. `adapter` defines the `LmsAdapter` interface. `blackboard` is the Learn REST client (OAuth, retries, paging, call log). `fake_blackboard` is an in-memory Learn server for tests and mock mode. `service` covers connect, link (code and term checks), push, pull into grading, and dry-run then passback. |
| `llm/` | The gateway: retries, rate limit, schema-validated JSON, logging. `embeddings.py` holds the embedders. |
| `jobs.py`, `job_handlers.py`, `worker.py` | Database-backed job queue for slow work |
| `auth.py` | Dev header sign-in or OIDC SSO |
| `audit.py`, `metrics.py` | Audit log; team metrics |

## Invariants (enforced in the API and covered by tests)

- No generation from an unlocked course version.
- A locked version is never edited; a change creates a new version.
- Only approved items export. Editing an approved item returns it to review.
- Every model call records provider, model and prompt version. Every item records the chunks it was grounded on.
- Real exam material reaches a hosted model only when `LLM_NO_RETENTION=true`.
- Faculty see only their own course versions, items, materials and jobs.
- No exam form exports unapproved. QA viewers never open an item or a form.
- Grading is off unless `GRADING_ENABLED`. Student identities are encrypted. Answers are anonymised before storage, and every prompt is checked against the roster's identity hashes before it is sent.
- A mark counts only when the faculty member confirms it. Release is refused while any mark is unconfirmed or the scale isn't confirmed. Bulk confirmation only covers unflagged answer-key marks. Overriding a confident suggestion by more than one level needs a reason. Only approved feedback is released. After release, marks change only through an appeal, which keeps the history.
- Student code runs only in the Docker sandbox.
- Blackboard: only approved forms are pushed. A link needs the same course code and term. A grade is written only when every mark is confirmed, after a dry run, and never over a grade changed in Blackboard unless asked. Every request is logged.

## Adding things

- **A validator rule:** add a function in `validation/rules.py`, register it in `_RULES`, and give it a stable `key`. Add a fixture case to `tests/synth/specs.py`.
- **An item type:**
  1. Add the schema in `drafts/schemas.py` and register it in `ITEM_MODELS`.
  2. Add a type rule in `drafts/prompts.py` and bump `GEN_PROMPT_VERSION`.
  3. Add rendering in `drafts/export.py` and `frontend/src/components/ItemView.tsx`.
  4. Add any per-type checks in `drafts/quality.py`.
- **A model provider:** implement `complete_json(system, user, schema, images=None)` in `llm/gateway.py` and add it to `build_provider`.
- **A migration:** `uv run alembic revision --autogenerate -m "..."`. CI checks that migrations match the models on Postgres.
