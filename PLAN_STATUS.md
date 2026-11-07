# Status against IMPLEMENTATION_PLAN.md

This file is for the team. It tracks each task in the plan (section 14) against the code: what's done, where the build deviates, and what's next. Update it with each change.

**Legend:**

| Mark | Meaning |
|---|---|
| ✅ | Done as planned |
| ⚠️ | Built, but deviates from the plan (being fixed, or kept on purpose with a reason) |
| ⏳ | Not started |
| 👥 | Needs people or university approvals, not code |

**Audit date:** 2026-11-06, after the plan replaced HANDOFF.md as the reference.
**Last update:** 2026-11-08, after the first-sight pass (dashboard with a KPI row, bar chart,
term readiness and next assessment; one four-step "Create a quiz or exam" flow; "Things to check"
rewritten in plain words with one-click fixes; a thirty-student grading demo; the glossary enforced
across the UI, the exports, the edit log and the API's error messages).

Previous: 2026-11-07, the faculty-usability pass (assessment reconciliation dialog, readable edit log,
next-steps panel, grounding fix, paper/key export split, Assessment Builder flow, light-red redesign).

## Deviations found in the audit

| # | Plan says | Built | Action |
|---|---|---|---|
| 0.1 | `worker/` job queue, `eval/`, Redis in compose | No worker, no eval, no Redis | Fix: DB-backed job queue + worker process; `eval/` harnesses |
| 0.2 | CI: ruff, eslint, mypy, tsc, tests, migration check | None | Fix: GitHub Actions workflow + eslint/mypy config |
| 0.5a | Gateway logs tokens; rate limiting | Logs model/prompt/latency only; retries but no throttle | Fix |
| 0.6 | `raw_text` + `source_location` (page/table/cell) per value | Raw text only for due dates | Fix: per-field source map |
| 0.8 | `eval/extraction.py` field-level scores vs gold | None | Fix |
| 1.6 | Normaliser is an LLM, schema-constrained | Deterministic mapper + LLM fallback only for unreadable sections | **Kept on purpose.** Plan 8.3 says "deterministic first, LLM only to label and normalise". The deterministic mapper meets every section 9 check on the real files, costs nothing and never invents values |
| 1.7 | Unknown date formats stay raw **and are flagged** | Kept raw, not flagged | Fix |
| 1.9 | Extraction runs in the worker; UI polls progress | Synchronous in the request | Fix (with 0.1) |
| 1.11 | Review screen shows the record beside the source (page image/table) | Source text in a separate tab | Fix (with 0.6) |
| 1.12 | Edit log viewable **and exportable** | Viewable only | Fix: CSV export |
| 1.13 | Faculty *choose a value* or dismiss with an **optional** note | Note required for errors; no "choose a value" | Fix |
| 1.15 | Roll-over offered when a new syllabus arrives | Manual "roll over" on a locked version | Fix: offer the previous term's version on upload |
| 2.7 | Generation runs as a job | Synchronous | Fix (with 0.1) |
| 2.8 | Duplicate check by embedding similarity | Lexical similarity | Fix once embeddings exist (2.2) |
| 2.9 | Filters: type, CLO, week, status, score | Type and status only | Fix |
| D1/D9/D12 | Grading, Blackboard, V13 now in later phases | README described them as out of scope | Fix docs |

## Task status

### Phase 0
| Task | Status |
|---|---|
| 0.1 Monorepo, worker, eval, compose | ✅ DB-backed job queue (`app/jobs.py`, `python -m app.worker`, compose `worker` service); `eval/`; local file storage. Deviation kept: Postgres queue instead of Redis/RQ — no extra service, works on SQLite in dev, SKIP LOCKED for many workers |
| 0.2 CI | ✅ `.github/workflows/ci.yml`: ruff, mypy (clean), pytest, Alembic upgrade/check/downgrade on Postgres+pgvector, synthetic extraction eval; eslint, tsc, build. Nightly (14.10): `.github/workflows/nightly-eval.yml` runs the extraction and generation evals with a local Ollama model (`NIGHTLY_MODEL`, default `qwen2.5:3b`) on synthetic syllabi only. It fails if fewer than 60% of generation requests give a draft passing every required check, and keeps the review sheet as an artifact. 👥 enable branch protection so red CI blocks merges |
| 0.3 Schema v1 | ✅ |
| 0.4 Auth stub + SSO adapter interface | ✅ (dev stub; OIDC in H.1) |
| 0.5 Gateway + adapters | ✅ Ollama, OpenAI-compatible (Gemini/Groq/OpenRouter), fake |
| 0.5a Gateway extras | ✅ logs provider, model, prompt version, latency, prompt/completion tokens; retries 429/5xx; per-model rate limit (`LLM_MAX_RPM`); every call needs a schema |
| 0.6 Extraction schema with source locations | ✅ `record.sources`: JSON Pointer → page/table/row/raw text, per row for page-split tables |
| 0.7 Gold labels for 20 syllabi | 👥 Harness and synthetic gold provided; real gold must be hand-written |
| 0.8 Eval harness | ✅ `eval/extraction.py` (field-level precision/recall per group + known-issue check); synthetic: 496/496 fields, 27/27 issues. `eval/make_gold_draft.py` writes drafts for 0.7 |
| 0.9 Wireframes with a pilot faculty member | 👥 |
| 0.10 Data-protection request | 👥 |
| 0.11 Blackboard API request | 👥 |

### Phase 1
| Task | Status |
|---|---|
| 1.1 Upload, SHA-256 | ✅ |
| 1.2 Section locator | ✅ (all core sections on the 4 real files) |
| 1.3 DOCX parser | ✅ |
| 1.4 PDF parser, page-split tables | ✅ |
| 1.5 Vision fallback | ✅ |
| 1.6 Normaliser | ⚠️ kept on purpose (see above) |
| 1.7 Dates | ✅ unreadable due dates raise V12 |
| 1.8 Persist as `extracted` | ✅ |
| 1.9 Async extraction | ✅ upload returns a job; UI polls and shows progress |
| 1.10 Validator V1–V12 | ✅ (all section 9 issues on the 4 real files) |
| 1.11 Review beside source | ✅ Source panel (page/table/row, original text, PDF page image) from flag evidence or any field's Source button |
| 1.12 Edit log export | ✅ CSV download. The log reads in plain English (operation, field label, before and after in words, `app/services/labels.py`); edits saved together are one row. The CSV keeps the raw path and JSON next to the readable columns |
| 1.13 Flag resolution | ✅ optional note; "choose a value" one-click fixes for V2 and V5 (logged edits). Plus a reconciliation view (`GET …/assessment-overview`) and one dialog per assessment that edits the weight table, the matrix and the schedule in a single save; a **Fix** button on every assessment flag |
| 1.14 Lock, new version | ✅ |
| 1.15 Semester view, roll-over | ✅ new upload offers the last locked version of the course and carries over its flag settlements; manual roll-over kept |
| 1.16 CLO–PLO coverage view | ✅ |

### Phase 2
| Task | Status |
|---|---|
| 2.1–2.4 Materials, chunking, embeddings, retrieval, licence guard | ✅ Materials page (PDF/PPTX+notes/DOCX/TXT/MD, kind, week); chunks ≈650 tokens with locations; embeddings via the gateway, local hashing embedder by default (`LLM_EMBED_MODEL` for Ollama/Gemini); pgvector on Postgres; retrieval test set 20/20 in top 5; textbooks blocked unless licensed; past exams never reach a hosted model unless `LLM_NO_RETENTION`. Note: similarity computed in Python (course-scale); switch to SQL ordering + HNSW when volumes grow. **Fixed:** the 0.05 relevance floor used to drop every chunk when the offline embedder scored a topical match near zero, so a course whose only material was one whole-course chapter never grounded anything. The floor now only filters while it still leaves something; otherwise the nearest pieces are used and the retrieval is reported as a weak match |
| 2.5 Item schemas | ✅ |
| 2.6 Request form | ✅ |
| 2.7 Generation | ✅ job; retrieved chunks in the prompt; items store `source_chunk_ids`, `grounded`, model, prompt version (now v4: MCQ Bloom capped at *analyze*, distractors from real misconceptions, one sub-topic per item in a batch). The generation request stores why retrieval grounded the batch or could not; `GET /api/drafts/{id}/grounding` returns the material titles, weeks, locations and excerpts behind a draft |
| 2.8 Quality checks | ✅ duplicates by embedding similarity (local embedder unless a hosted one may see exam items). Numeric keys use a safe AST evaluator instead of a sandboxed Python run (stricter; same goal) |
| 2.9 Review UI | ✅ filters: status, type, CLO, week, check result |
| 2.10 Export | ✅ Two documents: a student question paper and a separate faculty answer key (`part: paper | key`), one typeface at 11 pt, real headings, MCQ options as a hanging-indented lettered list, page numbers and the honor-code line in the footer. Checked by rendering the generated DOCX |
| 2.11 Metrics | ✅ `/team/metrics` (TEAM_EMAILS only): approval rate, edit size, light-edit rate (gate 2), rejection reasons, time to review, per type/course/prompt version |
| 2.12 Offline eval set | ✅ tooling: `eval/generation.py` writes a review sheet and scores it (≥80% gate); 👥 the team does the reviewing |
| 2.13–2.16 Lesson plan, case study, resource, rubric | ✅ |
| 2.17 Math (LaTeX) | ✅ `$…$`/`$$…$$` in any text; KaTeX in the UI; matplotlib mathtext images in DOCX/PDF; check warns on LaTeX that doesn't render |
| 2.18 Diagrams | ✅ Graphviz/PlantUML/Mermaid source in `figure.diagram`; must compile or the item fails (hard check); rendered into UI and exports. This dev machine has no renderer, so the check reports *skipped*; the Docker image installs Graphviz + PlantUML |
| 2.19 `code_exercise` + sandbox | ✅ new type (starter, solution, hidden tests); solution must pass in the sandbox before faculty see it (hard check), warning if the starter also passes. Sandbox: Docker (`--network none`, memory/CPU/pid limits, read-only) when available; time-limited subprocess fallback for dev, labelled *not isolated* |
| 2.20 Datasets and charts | ✅ `figure.dataset` (linear/normal/binomial/categorical, seeded) generated with numpy; charts drawn by matplotlib from the data; summary stats available to recomputed answer keys; CSV download |

### Hardening (14.4)
| Task | Status |
|---|---|
| H.1 SSO | ✅ OpenID Connect (authorization code + PKCE, JWKS-verified ID token, nonce/state, allowed email domains, signed httpOnly session cookie); tested against a fake IdP. 👥 needs AURAK IT to register the app (issuer, client id/secret, redirect URI) |
| H.2 Deployment provider | 👥 team decision; switching is config only (`LLM_PROVIDER`…); set `LLM_NO_RETENTION=true` only for a no-retention contract |
| H.3 Security | ✅ upload guard (macros, archive bombs, encrypted entries, bad archives), audit log (`audit_event`: sign-ins, uploads, locks, exports, downloads, materials), access-control tests, secrets in `.env`/env only; backups in the runbook. 👥 checklist sign-off |
| H.4 Accessibility | ✅ automated WCAG 2.1 AA audit (axe-core) on courses, review (including the assessment dialog), Draft Studio, materials and Assessment Builder (including the blueprint dialog), at 1440 px and 390 px: 0 violations. Dialogs are native `<dialog>` elements: focus starts on the first field, Escape closes, focus returns to the trigger. DOCX images carry alt text and exports use real headings. 👥 manual keyboard/screen-reader pass still needed |
| H.5 Performance | ✅ extraction 0.1–1.5 s per real syllabus (+ ~5–20 s for the V11 model call), far under 2 min. Generation timing depends on the chosen provider: measure after H.2 |
| H.6 Docs | ✅ `docs/faculty-quickstart.md`, `docs/ops-runbook.md`, `docs/architecture.md`. 👥 the 3-minute video |
| H.7 Pilot fixes | 👥 needs the pilot |

### Phase 3 (14.5)
| Task | Status |
|---|---|
| 3.1 Blueprint | ✅ derived from each assessment row (weeks up to the due week, CLOs mapped to it, time, total points, item mix, Bloom mix); faculty edit everything before building |
| 3.2 Exam builder | ✅ greedy selection with a repair pass (CLO shares, weeks, types, Bloom spread, no near-duplicates, time budget); gaps listed exactly ("1 more item for CLO 2, weeks 1–6") with a link to Draft Studio |
| 3.3 Parallel versions | ✅ N forms, minimal overlap, options shuffled per form, optional section labels |
| 3.4 Form review | ✅ reorder, swap, re-point (points kept summing to the total, largest remainder); approve; API refuses export of draft forms (test) |
| 3.5 Usage history | ✅ export records items with term and section; builder skips items used in the last N terms (default 2) and shows history per item |
| 3.6 QTI 2.1 | ✅ zip with manifest (MCQ, short answer, essay-style items) for forms and items. 👥 import into a Blackboard sandbox once IT grants one (13.C) |
| 3.7 Bank import | ✅ DOCX/PDF/TXT/QTI → `suggested` items; tags (CLO, week, Bloom) come from the **local** embedder, because old exams may not reach a hosted model (14.10); duplicate check against the bank; items without a key fail the schema check until faculty add one. 👥 the "≥80% tags accepted" check needs faculty |
| 3.8 Term-to-term comparison | ✅ diff on lock (CLOs, weights, assessments, weeks); approved items on changed/removed CLOs → `needs_review`; banner on the version page |
| 3.9 AI-solvability | ✅ job; model answers without key; code runs against hidden tests, numbers compared, others graded by a second call; trivial/partly/not plus AI-resistant suggestions; never blocks. Runs only with a model allowed to see exam items |
| 3.10 Shared banks | ⚠️ one bank per course instead of named `SharedBank`/`SharedBankMember` tables: an approved item is shared opt-in, and members are faculty with a locked version of the same course. Simplest rule that fits until **13.B** is decided; tests cover non-members |
| 3.11 Program coverage | ✅ PLO × course matrix (H/M/L + ABET "addressed"), term filter, wordings shown side by side |
| 3.12 QA viewer | ⚠️ viewers are configured by `QA_VIEWER_EMAILS` (signed in through SSO like everyone) rather than a `Viewer` table; scope is all programs. Access tests: a viewer gets 403 on every course, item and form route |

Verified end to end in the browser (lock → approve 4 → 2 parallel forms → approve → QTI download → coverage). Gate 3 percentages need the pilot (👥).

### Phase 4 (14.7)
**Built, and shipped off** (`GRADING_ENABLED=false`). 👥 The preconditions still stand before any real student work: data-protection approval (13.D), a provider/hosting that meets its conditions (`GRADING_LLM_APPROVED`), and ≥3 real calibration sets.

| Task | Status |
|---|---|
| 4.1 Sections, rosters, identities | ✅ `Section`, `Student` (random pseudonym), `StudentIdentity` Fernet-encrypted with `IDENTITY_KEY`, plus keyed hashes for lookup and the leak guard. Only the course's faculty member can re-identify; every re-identification is audit-logged. Tests: nothing in the clear at rest; another faculty member gets 404 |
| 4.2 Intake | ✅ CSV of typed answers (Q1…), or one PDF/DOCX/TXT per student (ID in the file name), or a ZIP; answers mapped to form positions; scoring runs as a job. A 40-student CSV takes seconds. Original files are not kept (data minimisation) |
| 4.3 Anonymisation | ⚠️ Roster-based plus pattern rules (labelled lines, "my name is", emails, phones, long IDs; name parts only when capitalised, so "will" survives a student called Will), **no NER model**. Second line of defence: every prompt is checked against the section's identity hashes and not sent if one matches. Red-team test with planted names, IDs, email, phone and a classmate's name: 100% stopped. Each scoring run writes a `grading_run` audit event (model, answers sent, answers blocked by the guard) for the Gate 4 audit |
| 4.4 Scale + V13 | ✅ Scale read from the syllabus (all 4 real files parse; CSCI 372's minus scale included). V13 checks contiguity, 0–100 coverage, overlaps and decreasing grade points, and runs only with grading on. Confirming a scale that differs from other locked syllabi of the term needs an explicit acknowledgement. Release requires a confirmed scale |
| 4.5 Key scoring | ✅ MCQ (mapped through each form's shuffled options; letter or option text), numeric with tolerance (final number; flagged if the right value is only in the working), exact short answer, blank = 0. No model. Calibration test: 100% agreement with the key |
| 4.6 Rubric suggestions | ✅ The rubric comes from the answer key (key points / method + answer / per question), scaled to the form's points. The model returns a level, quotes and a confidence per criterion. Quotes not found in the answer are dropped and noted. No evidence, low confidence (< 0.6) or a missing level → "needs faculty". Off unless `GRADING_LLM_APPROVED`; per type via `GRADING_SUGGEST_OFF` |
| 4.7 Code answers | ✅ Hidden tests run on student code **only in the Docker sandbox** (no network, limits); otherwise the cell is left for the faculty member. Test results are the evidence |
| 4.8 Consistency | ✅ Identical or near-identical (embedding ≥ 0.95) answers with different marks are listed per question |
| 4.9 Feedback drafts | ✅ Per question (key explanation, failing tests, or the model's rubric-referenced text) and overall (built from confirmed marks: score and CLOs to review). All start `suggested`; approve, edit or drop. Only approved feedback is released (test) |
| 4.10 Confirmation UI | ✅ Students × questions grid (suggested vs confirmed, amber = needs you). One-click confirm per cell. Bulk confirm only for unflagged answer-key cells. A reason is required to move a ≥ 0.8-confidence suggestion by more than one level (API-enforced) |
| 4.11 Release | ✅ ZIP with a Grade Center CSV, a marks detail with letters, and per-student feedback PDFs. Blocked until every cell is confirmed and the scale is confirmed. Release log in `grade_release` and the audit log. ⚠️ The Grade Center column/"Feedback Format" values need checking on the Blackboard sandbox (13.C) |
| 4.12 Appeals | ✅ Recorded per submission/question. The decision can re-mark, which is kept in the cell history. Released marks change only through an appeal |
| 4.13 Calibration | ✅ Calibration sets (CSV with answers + faculty marks, never releasable), scored by the normal pipeline. `eval/calibration.py` prints exact / within-one / QWK / MAE / leniency / length bias per type and exits 1 on a Gate 4 miss; the same table is in the UI. 👥 needs real anonymised Fall 2027 sets |

Verified in the browser on a demo with a fake model: lock → approve items → build and approve a quiz → confirm scale → section and roster → CSV upload (a signature became `[NAME]`) → bulk-confirm key marks → confirm the rest → approve feedback → release ZIP. axe audit of the grading, builder and coverage pages: 0 violations.

### Phase 5 (14.8)
**Built against a faithful fake Blackboard; shipped off** (`LMS_MODE=off`). 👥 It needs IT to register a Learn REST application and grant a sandbox course (13.C). Then set `LMS_MODE=blackboard` with the key, secret and redirect URI, and repeat the end-to-end run on the sandbox (Gate 5).

| Task | Status |
|---|---|
| 5.1 Adapter + OAuth | ✅ `LmsAdapter` interface; `BlackboardAdapter` on the public Learn REST API: 3-legged authorization code, so actions run as the faculty member; refresh tokens; tokens Fernet-encrypted. A fake Learn server (`app/lms/fake_blackboard.py`, httpx MockTransport) runs the same adapter code in tests and in `LMS_MODE=mock` |
| 5.2 Course linking | ✅ Faculty pick from their own Blackboard courses (instructor roles only). Course code and term must match the syllabus, or the link is refused. Tests cover the wrong term and the wrong course |
| 5.3 Push | ⚠️ Only approved forms (API-enforced). The REST API has no question-pool/test import, so a push creates the form's Grade Center column, and faculty import the QTI export (3.6) by hand. An existing column (e.g. the one Blackboard made for an imported test) can be attached instead. Revisit if the sandbox's Learn version offers an import endpoint |
| 5.4 Pull submissions | ✅ Text attempts of the linked column → Phase 4 intake: the latest attempt per student, roster entries created or updated, anonymised on arrival, then scored as a job. The result reports Blackboard attempts and students against stored submissions (test: 3 of 3). File attachments are a later step |
| 5.5 Grade passback | ✅ Only when every mark of the section is confirmed (and the scale is confirmed), else 409 with nothing written. A dry-run diff comes first. A grade changed in Blackboard since this tool last wrote it is skipped unless the faculty member ticks overwrite. Approved overall feedback goes with the grade. Every request is logged in `lms_sync.request_log`; a release record has channel `blackboard`. Re-runs write nothing new (test) |
| 5.6 Failure handling | ✅ Retries with backoff on 429/5xx, honouring Retry-After; token refresh on expiry or 401, saved; a minimum interval between calls; paging; per-student failures give a `partial` sync and a re-run writes only what's missing. A chaos test covers 429 + 503 + 500, expired tokens and one permanently failing student |

Verified in the browser with `LMS_MODE=mock`: connect, wrong course refused, link CSCI 372 (Spring 2026) with section S1, push, pull 3 students, confirm in Grading Assist, preview, write 3 grades, sync log. axe: 0 violations.

---

## Interface (14.11, added 2026-11-08)

The screens are judged against one rule: a teacher with no training, between
two classes, understands the screen in five seconds. `docs/ux-check.md` records
the check for every screen; `docs/design-references.md` records where each
pattern was borrowed from.

| Task | Status |
|---|---|
| Plain language everywhere | ✅ One glossary, applied to the UI, the exports, the edit log and the API's error messages. CLO → "learning outcome", the matrix → "the assessment table", flags → "Things to check", lock → "Confirm syllabus for this term", Draft Studio → "Question bank", suggested/under review/approved/rejected → New / Needs your review / Approved / Not used. Rule ids, model names, prompt versions and JSON pointers only inside "Details for the team" |
| Visual system | ✅ App background `#F7F8FA`, white cards and sidebar, AURAK crimson `#C41F32` for the one main action, seal gold as an accent only. 8 px grid, 10–12 px card radius, tabular numbers. No gradients, glow, glassmorphism, emoji or stock art |
| Shell | ✅ Fixed 248 px white sidebar, top header with search, notifications and profile, responsive card grid. `GET /api/dashboard`, `GET /api/search?q=`, `GET /api/notifications` with per-user read state |
| Dashboard | ✅ KPI row (first card solid crimson), "Questions this week" bar chart with the same numbers as a table, "Your courses" list, semi-circle term readiness, dark "Next assessment" block |
| Things to check | ✅ Plain title, one sentence with the values in words, one filled "Fix", a quiet "Keep as it is". "Fix" opens the prepared options as large radio cards with "Set it myself"; flags are never fixed automatically, and keeping one records the reason |
| One-step quiz creation | ✅ Four steps, one question each; `POST /api/course-versions/{id}/quizzes` writes the whole paper as one job. Review is Microsoft-Forms-shaped (Approve / Edit / Replace per question). Blueprint, bank re-use and equating stay behind "Advanced options" |
| Grading demo data | ✅ `fixtures/demo/` (a class list of 30 invented students and their answers to a 10-question STAT 100 paper, which `backend/scripts/demo_data.py` holds) and `backend/scripts/seed_demo.py`, idempotent against any database URL. In open-access mode the Grading page offers "Try it with a sample class of 30 students" |
| Accessibility | ✅ axe-core (`wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`) on 13 routes at 1440 px and 390 px: 0 violations. Keyboard-only run through the quiz flow and the Fix dialogs. No page-level horizontal scroll at 390 px on any route |

