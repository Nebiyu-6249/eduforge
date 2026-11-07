# AI Teaching Resource & Assessment Support Tool — Project Handoff

This file is the **only** context a new session gets. It holds everything decided so far. It covers what the project is, what is decided, what is not, the specs needed to build it, and what was learned from real sample syllabi.

- Status as of 2026-11-06: the specification is agreed. No code exists yet.
- The project is a student team project at **AURAK** (American University of Ras Al Khaimah, UAE).
- Deadline and workload are not constraints, per the team.

---

## 1. The brief (verbatim source of the project)

The project comes from row 7 of a university projects table:

| # | Title | Description | Techniques | Data sources |
|---|---|---|---|---|
| 7 | AI Teaching Resource & Assessment Support Tool | Faculty-controlled system for generating draft question banks, practice exercises, lesson plans, case studies, feedback prompts, and learning resources aligned *(text cut off in the source; assumed "with course learning outcomes")* | LLMs, structured prompting, outcome alignment, quality evaluation | Course learning outcomes, approved course content, sample instructor materials |

The team's raw feature list had 16 lines, five of them repeats:

1. Draft question banks
2. Draft lesson plans
3. Draft case studies
4. Draft practice exercises
5. Grade quizzes with feedback
6. Allow teachers to edit generated content
7. Mapping PLOs and CLOs
8. Automatic extraction
9. Syllabus to course
10. Feedback and grading
11. Courses per semester

---

## 2. One-paragraph summary

The project is a faculty-only web tool with these steps:

1. A faculty member uploads a syllabus that admin has **already vetted**.
2. The tool extracts a structured course record and **flags contradictions**.
3. The faculty member corrects fields, settles each contradiction, and **locks a working version** for that course and term.
4. The tool generates **CLO-tagged drafts** grounded in that working version and the faculty's approved materials.
5. The faculty member **edits, approves or rejects every draft**. Only approved items can be exported, as DOCX/PDF.

The governing rule: every AI output is a draft until a named faculty member approves it. Grading of student work is **not** in the initial deliverable.

---

## 3. Decisions log (binding — do not reopen without the team)

| # | Decision | Source |
|---|---|---|
| D1 | Grading and feedback **on student work** are out of the initial deliverable. They are a possible later "Phase 3". | Team |
| D2 | **No admin role or admin steps in the tool.** Syllabi are vetted by admin *before* upload, outside the tool. | Team |
| D3 | Faculty are the only users in Phases 1–2. They manage their own courses per semester. | Team |
| D4 | Everything comes from the uploaded vetted syllabus. That includes course info, CLOs, assessments, weights, weekly plan, PLOs and the CLO–PLO mapping. | Team |
| D5 | Faculty may edit extracted data. Edits are **logged, not routed for approval**. The edit log against the uploaded file is the audit trail. | Team |
| D6 | **Contradictions within a syllabus are settled by the faculty.** The faculty member then locks one version that becomes the system's working version. | Team |
| D7 | There is **no PLO master list.** PLOs are read from each vetted syllabus and stored with that course and term. Nobody maintains a central list. | Team |
| D8 | CLO–PLO mapping is **imported** from the syllabus, not invented by AI. | Agreed |
| D9 | **No Blackboard integration for now.** Export is DOCX and PDF files. (The team answered "that too" after "leave grading out of scope", read as "out of scope too". Confirm if in doubt.) | Team (interpreted) |
| D10 | **Free LLMs during development**, with the provider swappable at deployment. All model calls go through one gateway. | Team |
| D11 | No AI-disclosure work needed: "no action needed from outside". | Team |
| D12 | The grading scale in syllabi is irrelevant while grading is out of scope. | Team |
| D13 | English only. The syllabi state that English is the only classroom language. | Syllabi |

Proposed but **not yet accepted** features are listed in section 13. Ask the team before building them.

---

## 4. Modules (16 raw lines → 5 modules)

| Module | What it does | Raw list items | From the brief |
|---|---|---|---|
| 1. Course Registry | Uploaded syllabus → extracted record → validated → faculty corrects → **locked working version per course and term** | Automatic extraction, Syllabus to course, Mapping PLOs and CLOs, Courses per semester | Course learning outcomes as input |
| 2. Draft Studio | Generates drafts tagged to CLO, week and Bloom level, grounded in the locked record and approved materials | Question banks, practice exercises, lesson plans, case studies | Feedback prompts, learning resources |
| 3. Faculty Review | Edit, approve, reject, or regenerate with notes; version history; only approved items export | Allow teachers to edit generated content | "Faculty-controlled" |
| 4. Quality Checks | Validates every extracted syllabus. Scores every draft for CLO alignment, Bloom fit, answer-key correctness and duplication | — | Outcome alignment, quality evaluation |
| 5. Grading Assist (later, NOT initial) | Suggest marks and feedback on anonymised student answers, faculty confirms each | Grade quizzes with feedback, Feedback and grading | — |

"Feedback prompts" are generic per-question hints and explanations drafted with items. They use no student work, so they stay in Draft Studio. Remove them only if the team says so.

---

## 5. Scope

| Area | Phases 1–2 (initial deliverable) | Phase 3 (later) | Not planned |
|---|---|---|---|
| Courses | Registry, semester offerings, roll-over to the next term, CLO–PLO import and coverage report | Program-wide coverage | Changing official CLOs/PLOs outside governance |
| Content | Question banks and practice exercises first; then lesson plans, case studies, feedback prompts, learning resources | Item banks shared across sections | Student-facing chatbot or tutor |
| Assessment | Answer keys and rubrics for approved items; export as DOCX and PDF | Score suggestions and feedback on anonymised answers | Blackboard integration (for now) |
| Data | Vetted syllabi, faculty-approved course content | Student submissions | Commercial textbooks without a licence |
| Users | Faculty only | (QA/accreditation read-only, maybe) | Students, admins |

---

## 6. Workflow

There are two lanes: Faculty and System.

```
Faculty: Upload vetted syllabus (PDF/DOCX; term + course read from file)
   → System: Extract and validate (weights, CLO maps, PLO text; flags contradictions)
   → Faculty: LOCK WORKING VERSION  [gate 1] (correct fields, settle conflicts; edits logged)
   → Faculty: Request drafts (type, CLO, week, count)
   → System: Generate and check (grounded, tagged, scored)
   → Faculty: REVIEW EACH DRAFT  [gate 2] (edit / approve / reject)
        ↺ reject or "regenerate with notes" → System regenerates
   → (approved only) System: Export approved items (DOCX, PDF)

Later Phase 3, not initial: System suggests marks/feedback on anonymised answers → Faculty confirms every mark.
```

---

## 7. Data model (proposal; adjust freely)

```
Faculty(id, name, email)                       -- from SSO; the only user type
Program(id, code_or_name)                      -- as named in the syllabus appendix
Course(id, code, title, credit_hours, description, prerequisites)
CourseVersion(id, course_id, term, faculty_id, source_file_id,
              status: extracted|in_review|locked|superseded,
              locked_at, version_no)           -- ONE locked working version per course+term (see 13.D)
SourceFile(id, filename, mime, sha256, uploaded_by, uploaded_at)
CLO(id, course_version_id, number, text, bloom_verb?, bloom_level?)
PLO(id, course_version_id, program_id, number, text)        -- per syllabus, no master list (D7)
CLOPLOMap(clo_id, plo_id, strength: high|medium|low)        -- per program
AbetOutcomeAddressed(course_version_id, program_id, outcome_no)
Assessment(id, course_version_id, name, type, weight_pct, week?, due_date?, due_text_raw)
AssessmentCLO(assessment_id, clo_id, source: weight_matrix|weekly_schedule)
Week(id, course_version_id, week_no, topics[], readings[], clo_ids_listed[])
Resource(id, course_version_id, kind: textbook|other|web, citation, isbn?)
ValidationFlag(id, course_version_id, rule_id, severity, message, evidence_refs, resolution, resolved_by)
FieldEdit(id, course_version_id, field_path, old_value, new_value, edited_by, at)   -- edit log (D5)
Material(id, course_id, file_id, week_no?, kind: slides|notes|past_exam|other)      -- grounding
Chunk(id, material_id, text, embedding)                                          -- pgvector
Item(id, course_version_id, type, status: suggested|under_review|approved|rejected,
     clo_ids[], week_no?, bloom_level, difficulty, body_json, answer_key_json?,
     rubric_json?, feedback_prompts_json?, source_chunk_ids[],
     model, prompt_version, created_at)
ItemRevision(id, item_id, body_json, edited_by, at)
ReviewEvent(id, item_id, action: approve|reject|edit|regenerate, notes, by, at)
QualityScore(item_id, check, score, detail)
Export(id, course_version_id, format: docx|pdf, item_ids[], by, at)
```

Item types: `mcq`, `short_answer`, `problem`, `practice_set`, `lesson_plan` (per week), `case_study` (scenario, questions, teaching notes), `learning_resource`, `rubric`.

**Locking (design rule):** a locked CourseVersion is the working version. Changing it later creates a new version. Existing drafts keep the version they were generated from. Generation is allowed only from a locked version.

---

## 8. Syllabus extraction spec

### 8.1 Template

All AURAK syllabi follow one template, so extraction anchors on its section headings:

- Course Title, Course Code, Credit Hours, Semester and Academic Year, Class Timing(s), Method(s) of Instruction, Prerequisite course(s), Faculty Name, Contact Information and Office Hours
- Course Description, Additional Information about the Course
- Course Textbooks and Materials, Other Resources, Web Resources
- **Course Learning Outcomes (CLOs)**: a numbered table, "CLO 1 … CLO n"
- **Assessment Activities**: a weight table whose columns are assessments with %, plus a CLO × assessment "X" matrix
- Grading Scale (ignore while grading is out of scope)
- **Weekly Course Information**: columns Week | Topic | Required Readings | Assignment/Assessment (weight & due date) | Mapping of CLOs to Assessments
- Policies (attendance, accommodations, academic integrity, etc.): boilerplate, skip
- **APPENDIX**, which may repeat once per program:
  - the PLO list per program
  - a CLO→PLO mapping table with high/medium/low
  - an ABET outcomes "addressed in course" table (X marks or numbers)

### 8.2 What to extract

| Group | Fields |
|---|---|
| Course | code, title, credit hours, prerequisites, description, textbooks |
| Offering | term, class times, instructor |
| CLOs | number, text |
| Assessments | name, weight, week or due date, CLOs assessed |
| Weekly plan | week, topics, readings |
| Per program | PLO list, CLO→PLO strength, ABET outcomes addressed |

### 8.3 Parsing strategy

- **DOCX:** read tables directly (python-docx). Merged cells repeat, so dedupe by the underlying cell element. Deterministic first, LLM only to label and normalise.
- **PDF:** layout text first (pdftotext `-layout` or pdfplumber). Fall back to page images plus a vision-capable model when table structure is ambiguous.
- **LLM output:** must fill a fixed JSON schema. Never free text.
- **Dates:** normalise them. The samples use "10 February 2026", "12-October", "16-Nov", "23-09-2026" (DD-MM-YYYY), "W4", "Due Week 10" and "TBA". Keep the raw text alongside.

### 8.4 Validator rules (all are flags for faculty, never auto-fixes)

| Rule | Check |
|---|---|
| V1 | Weight-table weights sum to 100%. |
| V2 | Weights in the weekly schedule match the weight table (per assessment and per category). |
| V3 | Every assessment in the schedule has a weight-table category, and vice versa. |
| V4 | Assessment names are unique. |
| V5 | The CLO × assessment matrix agrees with the schedule's CLO column per assessment. |
| V6 | Every assessment has at least one CLO; every CLO is assessed at least once. |
| V7 | An ABET/PLO marked "addressed" has at least one CLO mapped to it, and vice versa. |
| V8 | An assessment isn't due, or mapped to a CLO, before the topic that CLO covers is taught (needs topic→CLO evidence, so best effort). |
| V9 | An in-class assessment's date falls on a class meeting day (from Class Timing). |
| V10 | Sections contain no leftover template text, e.g. "(See Syllabus Guide for additional information that should be added here)". |
| V11 | Course description and additional info are on-topic for this course. LLM check; catches paste-ins from another course. |
| V12 | Missing required fields (e.g. prerequisites blank). |

---

## 9. Sample syllabi findings

These are test fixtures; the files themselves are **not** included. The team must re-supply them. All are AURAK; four are Fall 2026 and one is Spring 2026.

| Course | File | Term | CLOs | Programs (PLO count) | Issues the validator must catch |
|---|---|---|---|---|---|
| CSCI 372 Compiler Design | PDF (MS Print-to-PDF; tables split across pages) | Spring 2026 | 4 | CS (6) | None internal. Its grading scale (A = 95–100 with minus grades) differs from Fall 2026's (A = 90–100, no minus grades); irrelevant while grading is out of scope. |
| CSAI 351 Data Science | DOCX | Fall 2026 | 3 | BS AI (7) | Two different assessments both named "Quiz #1" (10% wk5, 5% wk12): V4. ABET table marks PLO 6 addressed but no CLO maps to PLO 6: V7. Weeks 13–16 sit in a separate table. |
| CENG 411 Software Engineering | DOCX | Fall 2026 | 5 | CE (7), CS (6), AI & Data Science (7) | Midterm 25% in the weight table vs 20% in the schedule: V2. Four HWs at 5% each with no HW weight category: V3. IBM Certification 10% and Other Activities 10% missing from the schedule: V3. The AI&DS mapping table is fused with the ABET table into one malformed table. CLO5→PLO4 is Medium for CE but High for CS/AI. |
| CENG 401 Network Servers & Architecture | PDF | Fall 2026 | 4 | CE (7), CS (6) | "Additional information" describes embedded systems design, pasted from another course: V11. Quiz #2 and AWS Labs 2 and 4 have no CLO mapping, while week 12 has a mapping and no assessment (looks like a row shift): V5/V6. Template text left in: V10. Week 5 cell holds two assessments with one shared CLO list. |
| STAT 100 Intro Probability & Statistics | PDF | Fall 2026 | 5 | General Education (4) | CLO matrix vs weekly schedule disagree on **all six** assessments: V5 (details below). Quiz 1 (Wed 23 Sep), the Midterm (Mon 19 Oct) and Quiz 2 (Mon 9 Nov) fall on non-meeting days for a Tue/Thu class: V9. Prerequisites blank: V12. Garbled description text. Two sections (3:00 and 4:30 Tue/Thu). |

STAT 100 detail: CLOs per assessment, matrix vs schedule.

| Assessment | Matrix | Schedule |
|---|---|---|
| Quiz 1 | {1} | {1,2} |
| Quiz 2 | {2} | {1,4} |
| Midterm | {1,2} | {1,2,3} |
| HW1 | {1} | {2,3} |
| HW2 | {5} | {1,4} |
| Final | {2,3,4,5} | {3,4,5} |

HW2 maps to CLO 5 (regression) in the matrix but is due 2 Nov, before regression is taught (weeks 14–15).

Other facts:

- The AI program PLO 6–7 wording differs between CSAI 351 ("BS in AI") and CENG 411 ("AI and Data Science"). Under D7 this is just two separate per-syllabus lists, with no cross-syllabus flag.
- One syllabus can map to several programs, so the model must allow several PLO sets per course version (CENG 411 has three).
- Program PLO counts: CS 6 (ABET CAC 1–6), CE 7 (ABET EAC 1–7), AI 7, General Education 4.
- Textbooks are commercial (Aho et al.; Grus; Sommerville; Kurose & Ross) except STAT 100's OpenStax *Introductory Statistics*, which is openly licensed.

**Acceptance test seed:** the validator must raise each issue in the table above on these five files.

---

## 10. Draft generation and quality

- **Inputs per request:** locked CourseVersion, item type, target CLO(s), week(s), count, difficulty/Bloom target, optional faculty notes.
- **Grounding:** retrieve from that course's approved materials (pgvector). Every item stores its source chunk ids. If no material exists, generate from the syllabus only and mark the item "ungrounded".
- **Prompting:** one template per item type, versioned. Output is strict JSON per type schema.
- **Quality checks**, run before faculty see an item:
  - rule checks: schema, CLO exists in the locked version, week valid
  - LLM judge: CLO alignment and Bloom fit, scored with a rubric
  - answer keys recomputed: numeric answers in code, independent re-solve for others
  - duplicates: embedding similarity vs existing items
- Skills-type CLOs (e.g. "effective written and oral communication") get rubrics or activities, not MCQs.
- Review states are `suggested → under_review → approved | rejected`. An edit returns the item to review. Reject or "regenerate with notes" creates a new suggestion.

---

## 11. Architecture and stack (suggested)

```
Faculty web app (React) ── API & workflow (Python FastAPI: item states, permissions, audit log) ── University SSO
                                   │                                         └─ Export (approved only → DOCX/PDF)
        ┌──────────────────────────┼──────────────────────────┐
 Syllabus ingestion          Draft generation            Quality checks
 (DOCX tables, PDF layout    (template per type,         (rules, LLM judge,
  + vision fallback,          retrieval, CLO/week/        recomputed keys,
  JSON schema)                Bloom tags)                 dedup)
        └──────────────────────────┼──────────────────────────┘
   Shared platform: PostgreSQL (course DB) · LLM gateway (provider switch, logs model + prompt version) · Content store (files + pgvector)
```

- **LLM gateway:** one interface for all calls. Development uses free models (D10).
  - Free API tiers may use inputs for training [likely], so in development send only sample syllabi, never real exam items, or run an open-weight model locally (e.g. via Ollama).
  - At deployment, choose a no-retention provider.
- **Security:** role-based access (faculty sees own courses) and an audit log. Question banks count as test material under the AURAK Honor Code, so exposure must be controlled.

---

## 12. Delivery plan (proposed; dates assume the team started 9 Nov 2026)

| Phase | Dates | Content | Gate (proposed thresholds, team may change) |
|---|---|---|---|
| 0 Setup and data | 9 Nov – 4 Dec 2026 | Collect and label ~20 syllabi (PDF and DOCX); repo, schema, gateway | 20 labelled test syllabi ready |
| 1 Course Registry | 7 Dec 2026 – 29 Jan 2027 | Extraction, validator, correct/lock UI, terms, CLO–PLO import | ≥90% of extracted fields on unseen syllabi need no correction; validator catches all section 9 issues |
| 2 Draft Studio pilot | 1 Feb – 14 May 2027 (Spring pilot) | Question banks and practice exercises, then lesson plans, case studies, feedback prompts; review; quality checks; export | ≥70% of pilot drafts approved with light edits |
| 3 Grading Assist | Jun – Aug 2027 | Later and optional; not in the initial deliverable | Suggested marks match faculty marks on past anonymised work |
| Rollout of Phases 1–2 | ~6 Sep 2027 | | |

---

## 13. Open items

### A. Proposed features, NOT yet accepted (ask before building)

Recommended for the initial deliverable:

1. **Course materials library.** Upload slides, notes and past exams per course, tagged by week. This is what grounding needs; no module formally owns it yet.
2. **Built-in metrics.** Approval rate, edit size and rejection reasons per item type. Needed to judge the Phase 2 gate.
3. **Exam builder.** Assemble a draft quiz or exam from approved items to match the locked syllabus's assessment rows (weight, weeks, CLOs). Generate parallel versions for multi-section courses (STAT 100 runs two sections).
4. **Formulas, diagrams, code.** LaTeX (STAT 100), automata and parse trees (CSCI 372), UML/system models (CENG 411), and runnable, auto-checked code exercises (CSAI 351, CENG 401).
5. **Item usage history.** Which items went into which assessment and term.

After the pilot:

6. Import existing question banks.
7. Term-to-term syllabus comparison that flags items tied to changed CLOs.
8. An AI-solvability check for homework.

### B. Unresolved decision

When two instructors teach the same course in the same term, who locks the working version? Options are one version per section, or one per course and term. The current rule says one per course and term.

### C. Confirm

D9: is Blackboard integration out of scope, or wanted (import and/or API)?

---

## 14. Suggested first steps for the new session

1. Ask the team for the five sample syllabi (section 9) and any more vetted syllabi. Put them in `fixtures/syllabi/` (they hold faculty names and emails; don't commit them to a public repo).
2. Ask the team about open items 13.A–C.
3. Scaffold a monorepo:
   - `backend/`: FastAPI, SQLAlchemy, Alembic, PostgreSQL + pgvector
   - `frontend/`: React
   - `docker-compose.yml`
4. Build Phase 1 first:
   - extraction JSON schema
   - DOCX table parser
   - PDF layout parser
   - validator rules V1–V12, with unit tests that assert every section 9 issue is flagged
   - correct/lock UI with the edit log
5. Put the LLM gateway behind an interface with a free or local model adapter from day one.
