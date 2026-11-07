# EduForge: operations runbook

This is for the project team. There is no admin role in the tool (D2), so this file covers everything operational.

## Services

| Service | Command | Notes |
|---|---|---|
| API | `alembic upgrade head && uvicorn app.main:app` | Runs migrations on start (Dockerfile) |
| Worker | `python -m app.worker` | Runs extraction, generation and indexing jobs. Run several for throughput; on Postgres they never take the same job. On start, it re-queues jobs that a crashed worker left `running`. |
| DB | Postgres 16 + pgvector | `pgvector/pgvector:pg16` image |
| UI | Vite build served statically | `npm run build` → `frontend/dist` |

To run everything locally: `docker compose up --build`.

## Configuration

Set these as environment variables, or in `backend/.env`, which is git-ignored.

| Setting | Purpose |
|---|---|
| `DATABASE_URL` | Postgres URL (SQLite by default for development) |
| `STORAGE_DIR` | Uploaded files, plus cached page images under `pages/`. Back it up together with the DB. |
| `AUTH_MODE` | `dev` (header sign-in, never in production), `open` (hosted prototype: no sign-in, everyone is the shared account `OPEN_ACCESS_EMAIL`/`OPEN_ACCESS_NAME`), or `sso` |
| `NOTICE` | Banner text under the top bar, e.g. "Prototype: use made-up data only" |
| `STORAGE_BACKEND` | `fs` (files under `STORAGE_DIR`) or `db` (uploaded files in the database, for hosts that wipe their disk on restart, such as Render's free tier) |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI` | University SSO (plan H.1). The redirect URI must be registered with IT and end in `/api/auth/callback`. |
| `OIDC_ALLOWED_DOMAINS` | e.g. `["aurak.ac.ae"]` |
| `SESSION_SECRET` | 32+ random bytes; changing it signs everyone out |
| `COOKIE_SECURE=true`, `FRONTEND_URL`, `CORS_ORIGINS` | Production behind HTTPS |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL` | Model gateway (D10). Providers: `ollama`, `gemini`, `groq`, `openrouter`, `openai_compat` |
| `LLM_EMBED_MODEL` | Embedding model; empty = built-in local embedder |
| `LLM_MAX_RPM` | Rate limit per model (free tiers ≈ 5–15) |
| `LLM_NO_RETENTION` | Set `true` **only** for a provider contracted not to retain or train on inputs. Until then, past exams and exam items never go to a hosted model (plan 14.10). |
| `WORKER_MODE` | `external` in production (separate worker), `inline` for a single dev machine |
| `SANDBOX_MODE` | `docker` in production (code exercises; student code in Phase 4); never `subprocess` there |
| `TEAM_EMAILS` | Who can open the team metrics dashboard |
| `QA_VIEWER_EMAILS` | Read-only QA/accreditation accounts (plan 3.12): program coverage and syllabi, never items or exams |
| `GRADING_ENABLED` | Phase 4 Grading Assist. Leave `false` until the university's data-protection approval (13.D). While off, every grading route answers 403 and V13 doesn't run. |
| `IDENTITY_KEY` | Required when grading is on. A Fernet key that encrypts student identities at rest. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. **Keep it separate from the DB backups.** Losing it makes stored identities unreadable; leaking it together with a backup exposes them. |
| `GRADING_LLM_APPROVED` | `true` only when the configured provider/hosting is the one named in the data-protection approval. When off, answer-key and code marking still run, but open answers get no suggestion. |
| `LMS_MODE` | `off` until IT registers the Blackboard REST application (13.C); `mock` runs against a built-in fake Blackboard (development and demos only); `blackboard` for real |
| `BLACKBOARD_URL`, `BLACKBOARD_APP_KEY`, `BLACKBOARD_APP_SECRET`, `BLACKBOARD_REDIRECT_URI` | From IT's Learn REST application registration. The redirect URI ends in `/api/lms/callback`. Faculty tokens are encrypted with `IDENTITY_KEY`. |
| `GRADING_SUGGEST_OFF` | Item types whose suggestions missed the calibration gate, e.g. `["case_study"]`. They stay manual. |

## Routine tasks

- **Backups:** nightly `pg_dump` plus a copy of `STORAGE_DIR`. Test a restore every term.
- **Rotate the model API key:** change `LLM_API_KEY` and restart the API and workers. Every call is in `llm_call` (model, prompt version, tokens, latency, ok/error).
- **Rate limits:** a 429 shows on jobs as "rate-limited". The off-topic check (V11) falls back to a keyword check and says so. Lower `LLM_MAX_RPM` or change model.
- **Stuck jobs:** look at the `job` table (`status`, `error`). Restarting a worker re-queues `running` jobs.
- **Grading (Phase 4):** student identities are in `student_identity`, encrypted with `IDENTITY_KEY`. Every re-identification (roster view, release) is an `audit_event` with action `reidentify`. Releases are in `grade_release` (marks per pseudonym). Uploaded submission files are not kept: only anonymised answer text is stored. Each scoring run is a `grading_run` audit event saying which model received how many anonymised answers, and how many the identity guard blocked.
- **Audit:** `audit_event` holds sign-ins, uploads, locks, exports, downloads and material changes. Content edits are in `field_edit`; review decisions in `review_event` and `item_revision`.

## Evaluation (run each term)

```
cd backend
uv run python ../eval/extraction.py --synthetic   # parser regression check (CI runs this too)
uv run python ../eval/extraction.py               # real syllabi vs hand-checked gold in fixtures/gold
uv run python ../eval/generation.py SYLLABUS.pdf  # writes a review sheet for the team (plan 2.12)
uv run python ../eval/generation.py --synthetic STAT100 --min-pass 0.6   # what the nightly CI job runs (local Ollama model)
uv run python ../eval/generation.py --score generation_review.csv
uv run python ../eval/calibration.py              # Phase 4: suggested vs faculty marks; exit 1 if Gate 4 is missed
```

Repeat calibration every term on fresh anonymised samples (plan 14.9). Add any item type that drops below the gate to `GRADING_SUGGEST_OFF`.

Add new syllabi to `fixtures/` every term (plan 14.6). They hold faculty names, so keep them out of git.

## Incident checklist

1. **A wrong mark or item reached students?** Every export is recorded in `export` and `audit_event`, with who and which items.
2. **Suspected data leak to a model?** Check `llm_call` for the time window and provider. Exam material only goes out when `LLM_NO_RETENTION=true`. Student answers only go out when `GRADING_LLM_APPROVED=true`, after anonymisation, and a guard refuses any prompt that still holds a roster identity (the cell is then marked "Not sent to the model").
3. **A mark released by mistake?** Releases are in `grade_release` and `audit_event`. Correct it through an appeal (it keeps the history), then release again.
3. **Disable generation quickly:** set `LLM_PROVIDER=none` and restart. Uploads and review keep working.
