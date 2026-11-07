# AI Teaching Resource & Assessment Support Tool — Project Handoff (Full Scope)

This file is the **only** context a new session gets. It holds everything decided so far. It covers what the project is, what is decided, what is not, the specs needed to build it, and what was learned from real sample syllabi.

- Status as of 2026-11-06: the specification is agreed. No code exists yet.
- **Full-scope edition.** This version plans **every** feature, including those earlier put off: grading and feedback on student work, Blackboard integration, and all proposed extras (exam builder, formulas/diagrams/code, usage history, bank import, term-to-term comparison, AI-solvability check, shared banks, program-wide coverage).
- Phases 1–2 are unchanged. Phase 3 is built alongside summer hardening and ships with the first release (Sep 2027). Phases 4–5 follow, for a full release around Sep 2028. Section 3 records how each earlier decision is now treated.
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

After the initial deliverable, the tool grows in three steps:

- **Phase 3 (Assessment Builder):** build exams from approved items, track item use, import old banks, compare terms, check whether homework is trivially AI-solvable, share banks across sections, program-wide coverage.
- **Phase 4 (Grading & Feedback Assist):** suggest marks and feedback on student work; faculty confirm every mark.
- **Phase 5 (Blackboard integration):** push approved items and faculty-confirmed marks to Blackboard.

The governing rule: every AI output, including every suggested mark, is a draft until a named faculty member approves it.

---

## 3. Decisions log (binding — do not reopen without the team)

| # | Decision | Source |
|---|---|---|
| D1 | Grading and feedback **on student work** stay out of the initial deliverable. In this full-scope plan they are **Phase 4** (section 14.7). | Team; updated |
| D2 | **No admin role or admin steps in the tool.** Syllabi are vetted by admin *before* upload, outside the tool. | Team |
| D3 | Faculty are the only users in Phases 1–2. They manage their own courses per semester. Phase 3 adds an optional read-only QA/accreditation viewer. Students never log in; in Phase 4 they are data subjects only. | Team; extended |
| D4 | Everything comes from the uploaded vetted syllabus. That includes course info, CLOs, assessments, weights, weekly plan, PLOs and the CLO–PLO mapping. | Team |
| D5 | Faculty may edit extracted data. Edits are **logged, not routed for approval**. The edit log against the uploaded file is the audit trail. | Team |
| D6 | **Contradictions within a syllabus are settled by the faculty.** The faculty member then locks one version that becomes the system's working version. | Team |
| D7 | There is **no PLO master list.** PLOs are read from each vetted syllabus and stored with that course and term. Nobody maintains a central list. | Team |
| D8 | CLO–PLO mapping is **imported** from the syllabus, not invented by AI. | Agreed |
| D9 | **No Blackboard integration in the initial deliverable.** Export is DOCX and PDF. In this full-scope plan: a QTI file export in Phase 3, and API integration (item push, grade passback) in **Phase 5**. | Team; updated |
| D10 | **Free LLMs during development**, with the provider swappable at deployment. All model calls go through one gateway. | Team |
| D11 | No AI-disclosure work needed: "no action needed from outside". | Team |
| D12 | The grading scale in syllabi is irrelevant until Phase 4. From Phase 4 it **must** be extracted and validated (rule V13), because letter grades depend on it. | Team; updated |
| D13 | English only. The syllabi state that English is the only classroom language. | Syllabi |

All features that were earlier proposed or deferred are now **in scope** of this full plan; section 13 lists where each lands.

---

## 4. Modules (16 raw lines → 5 core modules, plus 2 later ones)

| Module | What it does | Raw list items | From the brief |
|---|---|---|---|
| 1. Course Registry | Uploaded syllabus → extracted record → validated → faculty corrects → **locked working version per course and term** | Automatic extraction, Syllabus to course, Mapping PLOs and CLOs, Courses per semester | Course learning outcomes as input |
| 2. Draft Studio | Generates drafts tagged to CLO, week and Bloom level, grounded in the locked record and approved materials | Question banks, practice exercises, lesson plans, case studies | Feedback prompts, learning resources |
| 3. Faculty Review | Edit, approve, reject, or regenerate with notes; version history; only approved items export | Allow teachers to edit generated content | "Faculty-controlled" |
| 4. Quality Checks | Validates every extracted syllabus. Scores every draft for CLO alignment, Bloom fit, answer-key correctness and duplication | — | Outcome alignment, quality evaluation |
| 5. Grading & Feedback Assist (Phase 4) | Auto-scores objective items from answer keys. For open answers, suggests a rubric level per criterion with quoted evidence, plus a feedback draft. Faculty confirm every mark | Grade quizzes with feedback, Feedback and grading | — |
| 6. Assessment Builder (Phase 3) | Builds quizzes/exams from approved items to match the locked syllabus's assessment rows; parallel versions; item usage history; bank import; term-to-term comparison; AI-solvability check; shared banks; program-wide coverage | (extends Question banks) | — |
| 7. LMS Integration (Phase 3 file, Phase 5 API) | QTI export of approved items; Blackboard REST: push question pools; pull submissions; pass back faculty-confirmed marks only | — | — |

"Feedback prompts" are generic per-question hints and explanations drafted with items. They use no student work, so they stay in Draft Studio. Remove them only if the team says so.

---

## 5. Scope

| Area | Phases 1–2 (initial deliverable) | Phase 3 Assessment Builder | Phase 4 Grading | Phase 5 Blackboard | Not planned |
|---|---|---|---|---|---|
| Courses | Registry, semesters, roll-over, CLO–PLO import, course coverage | Term-to-term comparison; program-wide coverage | Grading scale extracted (V13) | Course mapping to Blackboard course IDs | Changing official CLOs/PLOs outside governance |
| Content | Question banks, practice exercises, lesson plans, case studies, feedback prompts, resources, rubrics; materials library; formulas/diagrams/code | Shared banks across sections; bank import; AI-solvability check | — | Push approved pools | Student-facing chatbot or tutor |
| Assessment | Answer keys, rubrics, DOCX/PDF export | Exam builder, parallel versions, usage history, QTI export | Mark suggestions + feedback drafts; faculty confirm each | Pull submissions; pass back confirmed marks | Any mark posted without faculty confirmation |
| Data | Vetted syllabi, approved materials | Existing banks | Anonymised student submissions (after approval) | LMS data via official API | Commercial textbooks without a licence |
| Users | Faculty | + QA/accreditation read-only | Faculty (students are data subjects only) | Faculty | Students as users; admins |

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

Phase 3: Faculty picks an assessment row from the locked syllabus → System assembles a draft exam (+ parallel versions) from approved items → Faculty edits/approves → export (DOCX/PDF/QTI); usage recorded.

Phase 4: Faculty uploads submissions (or pulls them from Blackboard in Phase 5) → System anonymises, auto-scores objective items, suggests rubric levels + feedback for open answers, flags low confidence → FACULTY CONFIRMS EVERY MARK [gate 3] → marks released (CSV, or Blackboard passback in Phase 5).
```

---

## 7. Data model (proposal; adjust freely)

```
Faculty(id, name, email)                       -- from SSO; the only user type
Program(id, code_or_name)                      -- as named in the syllabus appendix
Course(id, code, title, credit_hours, description, prerequisites)
CourseVersion(id, course_id, term, faculty_id, source_file_id,
              status: extracted|in_review|locked|superseded,
              locked_at, version_no)           -- ONE locked working version per course+term (see 13.B)
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
Export(id, course_version_id, format: docx|pdf|qti, item_ids[], by, at)

-- Phase 3: Assessment Builder
AssessmentForm(id, assessment_id, version_label, status: draft|approved, blueprint_json, created_by)
FormItem(form_id, item_id, position, points)
ItemUsage(item_id, form_id, term, section?, used_at)          -- exposure history
BankImport(id, course_id, file_id, items_created, by, at)
VersionDiff(id, from_version_id, to_version_id, diff_json, affected_item_ids[])
SolvabilityCheck(item_id, model, solved: bool, detail)
SharedBank(id, course_id, name) / SharedBankMember(bank_id, faculty_id) / SharedBankItem(bank_id, item_id)
Viewer(id, name, email, scope: program|all)                  -- read-only QA/accreditation

-- Phase 4: Grading & Feedback Assist
Section(id, course_version_id, label, faculty_id)
Student(id, pseudonym, section_id)                            -- real identity held separately, encrypted
StudentIdentity(student_id, external_id_enc, name_enc)         -- separate table, access-logged
Submission(id, form_id, student_id, file_id?, answers_json, received_at, source: upload|blackboard)
ResponseScore(id, submission_id, form_item_id, method: key|llm|faculty,
              suggested_points, suggested_level?, evidence_quotes[], confidence,
              confirmed_points?, confirmed_by?, confirmed_at?, override_reason?)
FeedbackDraft(id, submission_id, form_item_id?, text, status: suggested|approved|rejected, approved_by?)
GradeRelease(id, form_id, by, at, channel: csv|blackboard)
Appeal(id, submission_id, reason, outcome, decided_by, at)
CalibrationSet(id, form_id, description) / CalibrationScore(calibration_id, submission_id, faculty_points, suggested_points)
GradingScale(course_version_id, letter, min_pct, max_pct, points)

-- Phase 5: Blackboard
LmsLink(id, course_version_id, lms_course_id, linked_by)
LmsSync(id, kind: pool_push|submission_pull|grade_push, status, request_log, at)
```

Item types: `mcq`, `short_answer`, `problem`, `practice_set`, `code_exercise` (starter code, solution, tests), `lesson_plan` (per week), `case_study` (scenario, questions, teaching notes), `learning_resource`, `rubric`. Bodies support LaTeX math and diagram sources (Graphviz/Mermaid/PlantUML) that render on export.

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
| V13 (Phase 4) | Grading scale bands are contiguous, cover 0–100 and don't overlap. Flag when it differs from the other syllabi of the same term (CSCI 372, Spring 2026: A = 95–100 with minus grades; Fall 2026 syllabi: A = 90–100, no minus grades). Faculty confirm which scale applies before any grade release. |

---

## 9. Sample syllabi findings

These are test fixtures; the files themselves are **not** included. The team must re-supply them. All are AURAK; four are Fall 2026 and one is Spring 2026.

| Course | File | Term | CLOs | Programs (PLO count) | Issues the validator must catch |
|---|---|---|---|---|---|
| CSCI 372 Compiler Design | PDF (MS Print-to-PDF; tables split across pages) | Spring 2026 | 4 | CS (6) | None internal. Its grading scale (A = 95–100 with minus grades) differs from Fall 2026's (A = 90–100, no minus grades). Irrelevant until Phase 4; then V13. |
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

## 12. Delivery plan (proposed; dates assume the team started 9 Nov 2026; task-level plan in section 14)

| Phase | Dates | Content | Gate (proposed thresholds, team may change) |
|---|---|---|---|
| 0 Setup and data | 9 Nov – 4 Dec 2026 | Syllabi collection and labels; repo, schema, gateway; **start the data-protection request for Phase 4 now** (long lead time) | 20 labelled test syllabi ready |
| 1 Course Registry | 7 Dec 2026 – 29 Jan 2027 | Extraction, validator, correct/lock UI, terms, CLO–PLO import | ≥90% of fields on unseen syllabi need no correction; all section 9 issues flagged |
| 2 Draft Studio pilot | 1 Feb – 14 May 2027 | Materials library, all item types incl. formulas/diagrams/code, quality checks, review, metrics, DOCX/PDF export | ≥70% of pilot drafts approved with light edits |
| Hardening + initial release | 17 May – 27 Aug 2027 | SSO, deployment provider, security, accessibility, docs | Dry run by a non-pilot faculty member |
| 3 Assessment Builder | 7 Jun – 27 Aug 2027 (parallel with hardening) | Exam builder + parallel versions, usage history, QTI export, bank import, term comparison, AI-solvability, shared banks, program-wide coverage, QA viewer | Built exams match their blueprint 100%; faculty accept ≥80% of built exams with light edits |
| Initial release (Phases 1–3) | ~6 Sep 2027 | | |
| 4 Grading & Feedback Assist | Build Sep – Dec 2027; calibrate on Fall 2027 work; pilot Jan – May 2028 | Submissions, anonymisation, auto-scoring, rubric mark suggestions, feedback drafts, confirmation UI, release, appeals | Calibration agreement targets in 14.7; zero marks released unconfirmed |
| 5 Blackboard integration | QTI from Phase 3; API Jan – May 2028 | Course linking, pool push, submission pull, confirmed-grade passback | End-to-end sync on a sandbox course; no unconfirmed mark ever written |
| Full release (all phases) | ~Sep 2028 | | |

---

## 13. Where each previously deferred or proposed feature lands

| Feature | Earlier status | Now |
|---|---|---|
| Course materials library | Proposed | Phase 2 (2A), required for grounding |
| Built-in metrics | Proposed | Phase 2 (2B), required for gate 2 |
| Formulas, diagrams, code | Proposed | Phase 2 (2B/2C) |
| Exam builder + parallel versions | Proposed | Phase 3 |
| Item usage history | Proposed | Phase 3 |
| Import existing question banks | Proposed, after pilot | Phase 3 |
| Term-to-term syllabus comparison | Proposed, after pilot | Phase 3 |
| AI-solvability check | Proposed, after pilot | Phase 3 |
| Shared banks across sections | Deferred | Phase 3 |
| Program-wide coverage + QA read-only viewer | Deferred | Phase 3 |
| Blackboard QTI file export | Out (D9) | Phase 3 |
| Grading & feedback on student work | Out of initial (D1) | Phase 4 |
| Grading scale extraction (V13) | Irrelevant (D12) | Phase 4 |
| Blackboard API (pools, submissions, grade passback) | Out (D9) | Phase 5 |

**Still unresolved:**

- **B. Multi-instructor courses.** When two instructors teach the same course in the same term, who locks the working version? The default is one version per course and term. Phase 3 shared banks and Phase 4 sections make this pressing; decide before task 1.14.
- **C. Blackboard environment.** Learn Original or Ultra? Will IT register a REST API application? Decide before Phase 5. If IT says no, Phase 5 shrinks to QTI export plus grade CSV import, both done by faculty.
- **D. Data protection for Phase 4.** University approval to process student work with an LLM; which provider/hosting; retention period. Request in Phase 0; Phase 4 cannot start without it.

---

## 14. Implementation plan (end to end)

This expands section 12 into buildable work. The phase numbers match section 12.

- **Calendar:** dates assume a start on 9 Nov 2026, AURAK's Spring term running roughly Feb–May 2027, and Fall 2027 starting early Sep.
- **Team:** the team is "multiple students", so work is split into four workstreams that run in parallel:

| Workstream | Owns |
|---|---|
| **BE** (backend/platform) | API, DB, auth, export, deployment |
| **EX** (extraction/validation) | parsers, extraction schema, validator |
| **AI** (generation/quality) | gateway, prompts, retrieval, quality checks, evaluation |
| **FE** (frontend/UX) | all screens, usability tests with faculty |

Every phase ends at a **gate**: a short review against written criteria. If a gate fails, the team fixes and re-runs it before the next phase's dependent work starts. Independent work may continue.

### 14.0 Before writing code (week 1)

1. **Get the inputs.**
   - The five sample syllabi from section 9.
   - As many more vetted syllabi as possible, both PDF and DOCX, from several departments. Target 25 or more: 20 for development, at least 5 held back as unseen test files.
   - Store them in a private location, never a public repo; they contain faculty names and emails.
2. **Get answers on open items 13.B (multi-instructor), 13.C (Blackboard environment) and 13.D (data protection).**
   - Default if no answer: locking is one version per course and term.
3. **Start the two long-lead requests now.** Both take months and Phases 4–5 cannot start without them:
   - the university data-protection/ethics approval to process student work with an LLM (13.D)
   - an IT request for a Blackboard REST API application in a sandbox course (13.C)
4. **Recruit 3–5 pilot faculty now** for Spring 2027. They need courses running that term and willingness to review drafts weekly. Ideally include a non-computing course such as STAT 100. Ask the same faculty now whether they will share anonymised Fall 2027 submissions for Phase 4 calibration.

### 14.1 Phase 0: Foundations (9 Nov – 4 Dec 2026)

| # | Task | WS | Done when |
|---|---|---|---|
| 0.1 | Monorepo: `backend/` (FastAPI, SQLAlchemy 2, Alembic, Pydantic v2), `frontend/` (React + TypeScript + Vite), `worker/` (job queue, e.g. RQ or Celery with Redis), `eval/`, `docker-compose.yml` (Postgres 16 + pgvector, Redis, MinIO or local file storage) | BE | `docker compose up` gives a running API, UI and DB on any team laptop |
| 0.2 | CI: lint (ruff, eslint), type-check (mypy, tsc), unit tests, migrations check on every PR | BE | CI is green on main and blocks merges on failure |
| 0.3 | DB schema v1 from section 7: Course, CourseVersion, SourceFile, CLO, PLO, Program, CLOPLOMap, Assessment, AssessmentCLO, Week, Resource, ValidationFlag, FieldEdit | BE | Alembic migration plus model unit tests |
| 0.4 | Auth: dev login stub now; SSO adapter interface (OIDC/SAML) for later. Role = faculty; a faculty member sees only their own courses. | BE | API rejects cross-faculty access, with tests |
| 0.5 | LLM gateway: one `complete(json_schema, messages, model_hint)` interface, with adapters for a local open model (Ollama) and one free hosted tier | AI | Swapping the adapter is config only |
| 0.5a | Gateway extras: logs model, prompt version, latency and tokens; retries and rate limiting; refuses calls without a schema | AI | Same as 0.5 |
| 0.6 | Extraction target schema (JSON Schema / Pydantic) covering every field in section 8.2, plus a `raw_text` and `source_location` (page/table/cell) for each value | EX | Schema reviewed by whole team |
| 0.7 | Labelled dataset: for 20 syllabi, hand-write the correct extraction JSON (the "gold" answers) and list every known contradiction (section 9 issues for the 5 samples) | EX + all | 20 gold files committed to private storage |
| 0.8 | Evaluation harness `eval/extraction.py`: field-level precision/recall/exact-match vs gold, per field group, plus a validator check that every known issue is flagged | AI | One command prints a score table |
| 0.9 | UX: low-fi wireframes for upload, review-and-lock, draft request, draft review | FE | Walked through with at least 1 pilot faculty |
| 0.10 | Data-protection request (13.D): data inventory, purpose, anonymisation design, retention, LLM provider/hosting, who can see identities | All | Request submitted to the university |
| 0.11 | Blackboard request (13.C): which Learn version, sandbox course, REST API application registration | BE | Request submitted to IT |

**Gate 0:** stack runs, CI green, 20 gold syllabi exist, harness runs (on an empty extractor it should report 0%), wireframes validated by a faculty member.

### 14.2 Phase 1: Course Registry (7 Dec 2026 – 29 Jan 2027)

**1A: Ingestion and extraction (7 Dec – 8 Jan)**

| # | Task | WS | Done when |
|---|---|---|---|
| 1.1 | Upload endpoint: PDF/DOCX only, size limit, SHA-256 dedupe, store SourceFile | BE | Rejects other types; same file is not stored twice |
| 1.2 | Section locator: split the document by the AURAK template headings (section 8.1), tolerant of case, spacing and numbering | EX | Finds all core sections in all 20 gold files |
| 1.3 | DOCX parser: tables via python-docx with merged-cell dedupe; join tables split across pages (e.g. CSAI 351 weeks 13–16) | EX | Tables match gold cell by cell |
| 1.4 | PDF parser: pdfplumber/pdftotext layout. Detect tables that repeat their header across pages (CSCI 372) and merge them. Mark low-confidence tables for vision fallback | EX | Tables match gold for the PDF samples |
| 1.5 | Vision fallback: render ambiguous pages to images and ask a vision-capable model for the table as JSON | AI | Used only when 1.4 flags low confidence; tracked in logs |
| 1.6 | Normaliser (LLM via gateway, schema-constrained): map parsed blocks into the extraction schema; split multi-assessment cells (CENG 401 week 5); read weights; read CLO lists; read high/medium/low mappings per program; keep `raw_text` | AI | Output always validates against the schema |
| 1.7 | Date normaliser (deterministic): handles every format in 8.3 and resolves "Week n"/"Wn" to a week number. Unknown formats stay raw and are flagged | EX | Unit tests for every sample format |
| 1.8 | Persist extraction as a CourseVersion with status `extracted`. Term and course come from the file (D3/D4); the offering is created automatically for the uploading faculty member | BE | Re-upload of a new term creates a new version, not an overwrite |
| 1.9 | Async job: extraction runs in the worker, with status polling and progress shown in the UI | BE/FE | A 14-page PDF does not block the API |

**1B: Validation, review and lock (11 Jan – 29 Jan)**

| # | Task | WS | Done when |
|---|---|---|---|
| 1.10 | Validator rules V1–V12 (section 8.4). V1–V10 and V12 are deterministic; V11 uses an LLM judge. Each flag stores rule id, severity, message and evidence (cells/pages) | EX/AI | Unit tests: every section 9 issue fires on its file; zero flags on a clean synthetic syllabus |
| 1.11 | Review screen (FE): extracted record shown section by section beside the source (page image or table), with flags pinned to fields | FE | Faculty can see why each flag fired |
| 1.12 | Inline edit; every change writes FieldEdit (old → new, who, when) (D5) | FE/BE | Edit log viewable and exportable |
| 1.13 | Flag resolution: faculty choose a value, or dismiss with an optional note. Resolution is stored on the flag (D6) | FE/BE | Unresolved blocking flags prevent locking |
| 1.14 | Lock: CourseVersion → `locked`; immutable afterwards. "Change" creates version n+1 copied from the locked one (section 7 rule) | BE | API refuses edits to a locked version; tests |
| 1.15 | Semester view: faculty's courses grouped by term; roll-over offers last term's locked version as a starting point when a new syllabus arrives | FE/BE | Two terms of one course shown separately |
| 1.16 | CLO–PLO import and coverage view: per program, a matrix of CLO × PLO with strength, plus which ABET outcomes are marked addressed (D7/D8) | FE | Matches the syllabus appendix for all 5 samples |

**Gate 1 (week of 25 Jan):**

- On at least 5 **unseen** vetted syllabi, ≥90% of extracted fields need no correction.
- All section 9 issues are flagged on the samples.
- A faculty member can go from upload to locked record in under 15 minutes on a typical syllabus (measured with a pilot faculty member).
- If below 90%: fix the weakest field group shown by the harness, then re-run. Do not start generation work on an unreliable registry.

### 14.3 Phase 2: Draft Studio and Spring pilot (1 Feb – 14 May 2027)

**2A: Materials and grounding (1 – 12 Feb)**

| # | Task | WS | Done when |
|---|---|---|---|
| 2.1 | Materials upload per course (slides PDF/PPTX, notes, past exams, DOCX), tagged by week and kind | BE/FE | Files listed per course and week |
| 2.2 | Text extraction plus chunking (by slide/heading, ~500–800 tokens), embeddings into pgvector. Embedding model goes through the gateway, local by default | AI | Re-index on new upload |
| 2.3 | Retrieval: filter by course and week range, then vector similarity; returns chunk ids | AI | Retrieval test set: for 20 topic queries, the right material appears in the top 5 |
| 2.4 | Licence guard: material kind "commercial textbook" is blocked from indexing unless the faculty member ticks "licensed" | BE | Enforced in API |

**2B: First item types plus quality checks, review and export (15 Feb – 12 Mar)**

| # | Task | WS | Done when |
|---|---|---|---|
| 2.5 | Item JSON schemas: `mcq`, `short_answer`, `problem`, `practice_set` (+ `answer_key`, `feedback_prompts`, `clo_ids`, `week_no`, `bloom_level`, `difficulty`, `source_chunk_ids`) | AI | Schemas versioned in repo |
| 2.6 | Request form: type, CLO(s) from the locked version only, week(s), count, difficulty/Bloom target, notes | FE | Can't pick a CLO that isn't in the locked version |
| 2.7 | Generation job: prompt template per type (versioned files), retrieval context, schema-constrained output, batch of N, status `suggested`. Items with no retrieved material are marked `ungrounded` | AI | Every item stores model + prompt version + chunks |
| 2.8 | Quality checks (section 10): schema and CLO validity; LLM-judge alignment and Bloom fit (score + reason); answer-key re-solve by a second call; numeric keys recomputed in a sandboxed Python run; duplicate check (cosine similarity threshold vs course items). Scores are shown to faculty, never hidden | AI | Check results visible on every item |
| 2.9 | Review UI: list with filters (type, CLO, week, status, score); item editor; approve, reject with a reason, or regenerate with notes; full revision history (ItemRevision, ReviewEvent) | FE/BE | An edit returns the item to `under_review` |
| 2.10 | Export: approved items only → DOCX and PDF (python-docx, then convert to PDF via LibreOffice headless or WeasyPrint). Student version without keys; faculty version with keys and feedback prompts | BE | Unapproved items are impossible to export (test) |
| 2.11 | Metrics: approval rate, edit size (character diff ratio between generated and approved text), rejection reasons, time-to-review — per type, course and prompt version. Dashboard for the team, not faculty | BE/AI | Numbers match a hand count on a sample |
| 2.12 | Offline eval set: 50 generated items per type, reviewed by the team against a written rubric before pilot faculty see anything | AI | ≥80% judged acceptable internally |

**2C: Pilot wave 1 and remaining types (15 Mar – 9 Apr)**

- Pilot faculty use question banks and practice exercises on their real Spring courses, reviewing weekly. Collect feedback in a shared log.
- In parallel, build the remaining types:

| # | Type | Notes |
|---|---|---|
| 2.13 | `lesson_plan` | per week, built from the locked weekly plan: objectives = CLOs, timing blocks, activities, materials links |
| 2.14 | `case_study` | scenario, questions, teaching notes |
| 2.15 | `learning_resource` | summary or study guide per topic |
| 2.16 | `rubric` | for projects and presentations; criteria × levels; used for skills-type CLOs such as communication (section 10) |
| 2.17 | Math | LaTeX in item bodies; rendered in the UI (KaTeX) and in exports; numeric keys still recomputed in code |
| 2.18 | Diagrams | Graphviz/Mermaid/PlantUML source in items (automata and parse trees for CSCI 372, UML for CENG 411, network diagrams for CENG 401); rendered to SVG/PNG for UI and export; the source must compile or the item fails its quality check |
| 2.19 | `code_exercise` | starter code, reference solution, hidden tests (Python first: CSAI 351; then sockets for CENG 401). The solution must pass its tests in a sandbox (container, no network, time and memory limits) before faculty see it |
| 2.20 | Charts and datasets | synthetic datasets with known properties (e.g. a regression with a set slope) for STAT 100 and CSAI 351; charts rendered from data, not drawn by the model |

**2D: Pilot wave 2 (12 Apr – 7 May):** all types in use; prompt iterations shipped weekly, each with a new prompt version so metrics compare versions.

**Gate 2 (10 – 14 May 2027):**

- ≥70% of pilot drafts approved with light edits (math, diagram and code items counted separately). "Light" = edit-size ratio ≤ 0.2; the team may set another value but must set it before the pilot starts.
- No unapproved item was ever exported.
- No validator-flagged contradiction reached generation unresolved.
- Pilot faculty say they would use it next term.
- Report the per-type results. A type that misses the bar ships later; it doesn't block the others.

### 14.4 Hardening and release prep (17 May – 27 Aug 2027)

| # | Task | WS | Done when |
|---|---|---|---|
| H.1 | Real SSO (with university IT): OIDC or SAML adapter from 0.4 | BE | Faculty log in with university accounts |
| H.2 | Deployment provider decision (D10): pick a no-retention LLM provider or a university-hosted open model; switch the gateway adapter; re-run eval sets to confirm quality didn't drop | AI | Eval scores within 5 points of pilot |
| H.3 | Security review: access control tests, audit log completeness, file-upload hardening (type sniffing, size, no macro execution), secrets management, backups | BE | Checklist signed off |
| H.4 | Accessibility: WCAG 2.1 AA for the UI; exports with headings and alt text | FE | Audit passes |
| H.5 | Performance: extraction under 2 min per syllabus; generation of 10 items under 3 min with the chosen provider | BE/AI | Measured |
| H.6 | Docs: faculty quick-start (one page plus a 3-minute video), admin-free ops runbook for the team, architecture README | All | Reviewed by a pilot faculty member |
| H.7 | Fixes from pilot feedback log; regression tests for every pilot bug | All | Log closed or deferred with reason |

**Gate R (end of August):** H.1–H.7 done; a dry run with a faculty member who wasn't in the pilot goes from upload to exported quiz without help.

### 14.5 Phase 3: Assessment Builder (7 Jun – 27 Aug 2027, parallel with hardening)

| # | Task | WS | Done when |
|---|---|---|---|
| 3.1 | Blueprint from the locked syllabus: for an assessment row (e.g. "Midterm 25%, weeks 1–7, CLO 1–2"), derive coverage targets: CLO share, weeks, Bloom mix, item count, time, total points. Faculty can edit the blueprint | AI/BE | Blueprint shown for every assessment of the 5 samples |
| 3.2 | Exam builder: select approved items to satisfy the blueprint (constraint solver or greedy with backtracking: CLO coverage, difficulty spread, no near-duplicates, time budget). Gaps are reported, with an offer to generate the missing items | AI | Built forms meet the blueprint, or state exactly what's missing |
| 3.3 | Parallel versions: N forms with equal blueprint coverage and similar difficulty, minimal item overlap (configurable), shuffled options | AI | Two forms for STAT 100's two sections with zero shared items when the bank allows |
| 3.4 | Form review: faculty reorder, swap and re-point items, then approve the form. Only approved forms export | FE/BE | Same invariants as items |
| 3.5 | Usage history: every exported form records its items with term and section. Builder warns about, or excludes, items used in the last N terms | BE | Warning shown in builder; history per item |
| 3.6 | QTI 2.1 export of approved items and forms (MCQ, short answer, essay), for manual Blackboard import | BE | Imports cleanly into a Blackboard sandbox (or a QTI validator if no sandbox yet) |
| 3.7 | Bank import: DOCX/PDF/QTI question files → items with status `suggested`. The AI tags CLO, week and Bloom; faculty review as usual. Runs duplicate detection against the existing bank | EX/AI | 100 imported questions tagged; faculty accept ≥80% of tags |
| 3.8 | Term-to-term comparison: when a new version is locked, diff it against the previous locked version (CLOs, weights, assessments, weeks). Approved items tied to changed or removed CLOs go to `needs_review` | BE | Diff correct on a synthetic changed syllabus |
| 3.9 | AI-solvability check: run each homework/project item through one or two strong models without help. Report "solved trivially / partly / not". Suggest AI-resistant variants (personal data, oral follow-up, process evidence) | AI | Report shown per item; never blocks approval |
| 3.10 | Shared banks: faculty teaching the same course can share approved items into a course bank (opt-in per item). Uses the 13.B decision | BE/FE | Sharing permissions tested |
| 3.11 | Program-wide coverage: across all locked versions of one program's courses in a term, a PLO × course matrix with strengths and ABET outcomes. Because PLOs are per syllabus (D7), PLOs are matched across courses by program + number; wording differences are shown, not resolved | BE/FE | Matrix for CS from CSCI 372, CENG 401, CENG 411 |
| 3.12 | QA/accreditation viewer: read-only role seeing coverage and syllabi data, never items or exams | BE | Access tests: viewer cannot open any item |

**Gate 3 (end Aug 2027):**

- 100% of built forms meet their blueprint or list their gaps.
- Pilot faculty accept ≥80% of built exams with light edits.
- QTI imports cleanly.
- Usage warnings fire on reused items.

### 14.6 Initial release (Phases 1–3) (~6 Sep 2027, Fall 2027)

- Open to all faculty, or the departments the team picks.
- Office hours in the first 3 weeks.
- Monitor the metrics dashboard and error logs weekly.
- Collect new syllabi into the eval set every term.
- **Collect Phase 4 calibration data this term:** with the approval from 0.10, pilot faculty provide anonymised Fall 2027 submissions with their own marks.

### 14.7 Phase 4: Grading & Feedback Assist (build Sep – Dec 2027; pilot Jan – May 2028)

**Preconditions (all required):** data-protection approval granted (13.D); deployment LLM provider meets its conditions (no retention, approved hosting); at least 3 calibration sets of real anonymised submissions with faculty marks.

**4A: Data and anonymisation (Sep – Oct 2027)**

| # | Task | WS | Done when |
|---|---|---|---|
| 4.1 | Sections and rosters: Section per course version; Student with pseudonym. Real identity in a separate encrypted table (StudentIdentity) with access logging; only the course's faculty member can re-identify | BE | Identity never leaves the DB; access log tested |
| 4.2 | Submission intake: per approved form, upload a CSV of typed answers, one file per student (PDF/DOCX), or a ZIP. Map answers to FormItems. Handwritten scans are a later stretch (OCR, lower gate) | BE/EX | Intake of a 40-student quiz in under 5 minutes |
| 4.3 | Anonymisation before any model call: strip names, IDs and emails from answer text (pattern rules plus NER); pseudonym only. Test that no identity reaches the gateway | AI | Red-team test with planted identities passes 100% |
| 4.4 | Grading scale extraction and V13; faculty confirm the scale per course version | EX | Scale confirmed before any release |

**4B: Scoring and feedback (Oct – Dec 2027)**

| # | Task | WS | Done when |
|---|---|---|---|
| 4.5 | Objective auto-scoring (MCQ, numeric with tolerance, exact short answer): deterministic from the approved answer key, **no LLM**. Faculty still confirm, in bulk | BE | 100% match with key on test data |
| 4.6 | Open-answer suggestion: per rubric criterion, the model suggests a level and points, quotes evidence from the answer, and gives a confidence. Low confidence or missing evidence → flagged "needs faculty" | AI | Every suggestion carries quotes and confidence |
| 4.7 | Code answers: run student code against the item's hidden tests in the sandbox; test results become evidence; style/explanation criteria use the rubric path | AI | Sandbox limits enforced; no network |
| 4.8 | Consistency check: compare suggested marks across similar answers; flag outliers (same answer, different mark) | AI | Outliers listed per item |
| 4.9 | Feedback drafts: per student and per item, short, rubric-referenced, actionable. Status `suggested`; faculty approve, edit or drop | AI/FE | Feedback never released unapproved |
| 4.10 | Confirmation UI: grid of students × items; suggested vs confirmed; one-click confirm, edit with an optional reason (an override reason is required when changing a high-confidence suggestion by more than one level); bulk confirm only for key-scored items | FE | Release blocked until every cell is confirmed |
| 4.11 | Release: marks + approved feedback → CSV (Blackboard Grade Center format) and per-student PDF feedback. Phase 5 adds direct passback | BE | Release log; no unconfirmed mark in any file (test) |
| 4.12 | Appeals: record an appeal, the decision and who decided; re-marks keep history | BE/FE | History visible per submission |
| 4.13 | Calibration harness: on each calibration set, compare suggested vs faculty marks: exact level agreement, within-one-level agreement, quadratic weighted kappa (QWK), mean absolute error in points; also bias checks (e.g. answer length vs mark) | AI | One command prints the table |

**4C: Pilot (Jan – May 2028)**

- Pilot faculty use Grading Assist on real Spring 2028 quizzes and homework. Every mark is faculty-confirmed.
- Track: time saved per submission, override rate per item type, flagged-rate, feedback approval rate.

**Gate 4 (May 2028)** (team sets final thresholds before calibration starts; proposed):

- On calibration sets: within-one-level agreement ≥90% and QWK ≥0.8 for open answers; 100% for key-scored items.
- No identity ever reached a model (audit).
- Zero marks or feedback released unconfirmed.
- Pilot faculty report time saved. Item types that miss the bar stay "suggest-off" (manual marking UI only).

### 14.8 Phase 5: Blackboard integration (QTI from Phase 3; API Jan – May 2028)

**Precondition:** IT registers the REST API application and grants a sandbox course (13.C). If refused, Phase 5 = QTI export (3.6) + Grade Center CSV (4.11) only, and stops here.

| # | Task | WS | Done when |
|---|---|---|---|
| 5.1 | Blackboard adapter behind an `LmsAdapter` interface (so another LMS could be added). OAuth 2 with the registered app; per-faculty authorisation (3-legged) so actions run as the faculty member | BE | Faculty connect their Blackboard account |
| 5.2 | Course linking: map a course version + section to a Blackboard course ID (faculty pick from their own Blackboard courses) | BE/FE | Link saved; wrong-course protection (code and term must match) |
| 5.3 | Push approved items/forms as question pools or tests (or via QTI upload where the REST API lacks it); never push unapproved content | BE | Pool appears in the sandbox course |
| 5.4 | Pull submissions for a linked assignment/test into Phase 4 intake, anonymised on arrival | BE | Pulled submissions match Blackboard counts |
| 5.5 | Grade passback: write **only confirmed** marks to the Grade Center column; dry-run diff shown first; every write logged (LmsSync). Never overwrite a grade the faculty changed in Blackboard without asking | BE | Sandbox end-to-end test; idempotent re-run |
| 5.6 | Failure handling: retries, partial-failure report, rate limits, token expiry | BE | Chaos test on the sandbox |

**Gate 5:**

- End-to-end on a sandbox course: link → push pool → pull submissions → suggest → confirm → passback.
- Zero unconfirmed or unapproved writes (log audit).
- One pilot faculty member completes it on a real course.

### 14.9 Full release (~Sep 2028)

- Enable Phases 4–5 for the faculty and item types that passed their gates; everything else stays as in the initial release.
- Repeat calibration every term on fresh anonymised samples. Disable suggestions for any item type whose agreement drops below the gate.

### 14.10 Cross-cutting rules for the whole build

- **Tests:**
  - Each validator rule and parser has unit tests driven by the section 9 fixtures.
  - The extraction and generation eval sets run in CI nightly (with a local model), so regressions show up before merge to main.
- **Prompts are code:** prompts live in versioned files, changes go through PR, and each item records the prompt version.
- **Faculty-in-the-loop invariants, enforced in the API (not just the UI) and covered by tests:**
  - no generation from an unlocked version
  - no export of unapproved items
  - no silent overwrite of a locked version
  - no exam form exported unapproved (Phase 3)
  - no student identity sent to any model; no mark or feedback released, or written to Blackboard, without faculty confirmation (Phases 4–5)
- **Data hygiene:** only sample syllabi go to free hosted models (section 11). Real exam items only go to local models or the chosen no-retention provider. Student work only goes to the provider/hosting named in the data-protection approval, after anonymisation.
- **Decision points:** 13.B before 1.14 (lock) and again before 3.10 (shared banks); 13.D requested in Phase 0, required before 4.1; 13.C requested in Phase 0, required before 5.1.

### 14.11 First actions for the new session

1. Ask the team for the syllabi (14.0 step 1) and answers to 13.B–D. Make sure the data-protection and Blackboard requests (0.10, 0.11) go out in the first weeks.
2. Do 0.1–0.3 (scaffold, CI, schema) and 0.6 (extraction schema) first. Then start the gold labels (0.7) with the team, since everything after depends on them.
