# The five-second check

Every screen in EduForge is opened by a teacher who has had no training, is
between two classes, and will give it about five seconds before deciding
whether to carry on or close the tab.

So each screen has to answer three questions in those five seconds:

1. **What is this?** — a heading in words a teacher already uses.
2. **What do I do next?** — one filled crimson button. Everything else on the
   screen is quieter than it.
3. **What happens if I press it?** — a sentence under the heading that says so,
   before the press rather than after.

A screen fails the check if the first thing the eye lands on is a table, a
status pill, a rule id, or two buttons of equal weight.

This file records the check for every screen, and what had to change to pass
it. It was last walked through on 8 November 2026 at 1440 px and 390 px.

---

## Dashboard — `/`

| | |
|---|---|
| What is this? | "Welcome back, *name*" and "Here is where Fall 2026 stands." |
| What do I do next? | **Upload a syllabus** — the only filled button above the fold. |
| What happens? | The next-assessment block names the quiz and the date, and its button says **Prepare this quiz**. |

The four KPI cards read as sentences, not metrics: "Things to check — 2 — Found
in syllabuses you have not confirmed yet". The first card is solid crimson so
the row has an obvious starting point.

**Changed for this check:** the bar chart carries "Show these numbers as a
table" underneath, so the week's figures are readable without reading a chart.

## My courses — `/courses`

| | |
|---|---|
| What is this? | "My courses", then "One syllabus per course and term." |
| What do I do next? | **Upload a syllabus**. |
| What happens? | The state column says **Confirmed** or **Being checked**, not a code. |

Replaced versions are behind "Show 1 replaced version" rather than mixed into
the list.

**Changed for this check:** at phone width the table scrolls inside its own
card; the page itself never scrolls sideways.

## Course overview — `/v/{id}`

| | |
|---|---|
| What is this? | The course code and title, then the term and whether it is confirmed. |
| What do I do next? | **Confirm syllabus for this term**, disabled with a reason until nothing must-fix is left. |
| What happens? | The five-step bar across the top shows where this course has got to. |

The right-hand "What EduForge read" column is a summary, not a form: counts
only, with the link into the syllabus.

## Things to check (on the overview and the syllabus page)

| | |
|---|---|
| What is this? | "Things to check", a progress bar, and "*n* of *m* done". |
| What do I do next? | One **Fix** button per card. |
| What happens? | "EduForge never changes your syllabus on its own." |

Each card is a plain title ("Two assessments have the same name"), one sentence
that spells out the values in words ("Quiz #1 in week 5, worth 10% and Quiz #1
in week 12, worth 5%"), one filled **Fix**, and a quiet **Keep as it is** link.
The rule id, the technical message and the JSON pointers are inside **Details
for the team**.

**Changed for this check:**

- The per-card severity line was removed. The cards sit under a "Must fix
  before confirming (2)" heading, so repeating it on every card was noise.
- "Fix" opens the prepared options as large radio cards whenever a rule has
  them, with **Set it myself** as the last option. Before, some rules sent the
  teacher straight into the full form.
- Pressing **Fix** from the overview used to change the route, which threw away
  the "open this assessment" instruction before the dialog could appear. The
  instruction now travels with the navigation.
- "A program outcome…" became "A programme outcome…", to match the sentence
  under it.

## Syllabus — `/v/{id}/syllabus`

| | |
|---|---|
| What is this? | The course heading, and a tab per part of the record. |
| What do I do next? | **Create a quiz or exam**. |
| What happens? | Each field has **Source**, which shows the line it was read from. |

Tabs are named for what they hold: Course details, Learning outcomes,
Assessments, Weekly plan, Programme outcomes, Coverage, Text from the file,
Changes you made.

**Changed for this check:** every remaining "CLO" and "PLO" in the tables
became "Outcome" and "Programme outcome", including the mapping grid, the
coverage tables, the chips in the weekly plan and the edit log.

## Create a quiz or exam — `/v/{id}/quiz/new`

Four steps, one question each, in the GOV.UK pattern. Every step has **Back**
and **Continue**, and Continue is the only filled button.

| Step | What is this? | What do I do next? |
|---|---|---|
| 1 | "What are you making?" | Pick a row from the syllabus, or "Practice questions". |
| 2 | "What should it cover?" | Tick weeks and learning outcomes (filled in already from the row). |
| 3 | "How many of each type?" | Set the counts; the running total says "*n* questions · *n* points · about *n* minutes to sit". |
| 4 | "Write the questions" | **Write them** — one request, all of it at once. |

Step 2 says plainly when there are no slides: "Questions will be written from
the syllabus only. Adding your slides makes them follow your own wording."
Builder-only controls (blueprints, re-use from the bank, equating sets) are
behind **Advanced options** on step 3.

**Changed for this check:** the count steppers lost presses when tapped
quickly, and the step bar could not be scrolled by keyboard at phone width.

## Quiz review

Microsoft Forms' shape: one card per question, the correct option marked on the
option itself, points on the card. Three actions per card — **Approve**,
**Edit**, **Replace** — and a bar at the bottom that counts them ("3 of 5
approved") with the one action that matters, **Approve this paper**.

A question that fails its own checks cannot be approved, and the card says why
in a sentence rather than a code.

## Question bank — `/v/{id}/questions`

| | |
|---|---|
| What is this? | "Question bank — browse and reuse your approved questions." |
| What do I do next? | **Write them**, under the short form at the top. |
| What happens? | Each draft is listed with its outcome and its state. |

States read **New**, **Needs your review**, **Approved**, **Not used**.

**Changed for this check:** the list preview showed raw TeX
(`$\text{mean}=75.0$`). The preview now strips the markers, so a teacher
skimming sees "mean=75.0". The full question is still typeset in the panel.

## Marking — `/v/{id}/grading`

| | |
|---|---|
| What is this? | "Marking · STAT 100", then "EduForge suggests a mark for every answer. **You confirm each one**, and nothing reaches a student until you do." |
| What do I do next? | Whichever of the four steps is still open. |
| What happens? | The grid colours a cell green once you have confirmed it. |

Four steps: Add your students, Add their answers, Check the suggested marks,
Release the marks. The side panel shows one student's answer with the
suggestion, the reason, and a points box.

**Changed for this check:** the scale table and the class table now scroll
inside their cards at phone width instead of pushing the page sideways.

## Reports — `/reports`

| | |
|---|---|
| What is this? | "Programme coverage — which programme outcomes each confirmed syllabus covers this term." |
| What do I do next? | Pick a programme and a term. |
| What happens? | H, M and L are explained under the table, in the same screen. |

**Changed for this check:** the page described itself as "PLO × course … (they
are separate per-syllabus lists, D7)". A decision-log reference is not a
sentence for a teacher; it was replaced with what the table shows.

---

## What is checked on every screen

- **One main action.** One filled crimson button. If a card needs more than
  three, the rest go behind **More** or a disclosure.
- **No jargon on the surface.** CLO, PLO, rule ids, model names, prompt
  versions, JSON pointers and raw file paths live inside **Details**. The
  glossary in the brief is the authority; the edit log, exports and error
  messages follow it too.
- **Messages say three things.** What happened, why it matters, what to do.
- **No emoji, no gradients, no glow, no stock art.**
- **Phone width.** Off-canvas sidebar, single-column forms, tables that scroll
  inside their card, and no page-level horizontal scroll. Checked by comparing
  `documentElement.scrollWidth` with `clientWidth` on every route at 390 px:
  all equal.
- **Accessibility.** axe-core with the `wcag2a`, `wcag2aa`, `wcag21a` and
  `wcag21aa` rule sets, on every route at 1440 px and 390 px: zero violations.
  Every interactive element is reachable by Tab in reading order and draws a
  visible focus ring. Dialogs trap focus, close on Escape and return focus to
  the control that opened them.

To re-run the accessibility check locally:

```bash
cp frontend/node_modules/axe-core/axe.min.js frontend/public/axe.min.js
```

then, in the browser console on any page, load `/axe.min.js` and call
`axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } })`.
The copied file is git-ignored; it is an audit tool, not part of the app.

## Round 3 additions (2026-11-08)

### Quizzes and exams — `/v/{id}/quiz`

| | |
|---|---|
| What is this? | "Quizzes and exams — every quiz and exam for STAT 100, under the syllabus row it is for." |
| What do I do next? | **New quiz or exam** (the one filled button), or **Create** next to a syllabus row that has nothing yet. |
| What happens? | Each paper says where it is: "Writing… about 1 minute left" with a bar, "3 of 5 approved", "Ready to download" or "Couldn't finish", with one action. |

### One quiz — `/v/{id}/quiz/{form}`

While it is written: "You can leave this page. We'll keep writing and let you
know when it's ready", a progress bar, "2 of 5 written · about a minute left",
and the questions written so far. When it is written, the review described
above. If it could not be finished: the reason in a sentence and **Try again**,
which reopens the flow with the same choices.

### Work in progress (clock icon, top right)

| | |
|---|---|
| What is this? | "Work in progress": what is running, with a bar and the time left, and what finished today. |
| What do I do next? | **View** or **Open** next to a piece of work; **Try again** for one that failed. |
| What happens? | When something finishes while you are on another page, a note appears bottom right with **Open**. |

### Question bank (changed)

Each question carries a label for the quiz it is in ("Quiz 2 · A") or "Not in a
quiz yet". The list is grouped by quiz or exam by default (also by week or
outcome), and filters by "Used in". Downloads act on the questions you tick.

### Slides and materials (changed)

| | |
|---|---|
| What is this? | "Add your slides and notes. New questions will follow your own wording." |
| What do I do next? | **Choose files** (or drop files on the box). |
| What happens? | One row per file: Uploading 40% · less than a minute left, then Reading the file, then Ready, or "Couldn't read this file: the reason" with Try again. |

### Marking (changed)

The four steps first, then which paper and which class, then one card per step;
the current step is open and outlined. With answers in but no suggestions yet,
step 3 says so in a sentence and offers **Suggest marks**; while marks are being
worked out, a banner shows the time left and the grid fills in.
