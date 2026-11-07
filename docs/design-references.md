# Where the interface comes from

EduForge is used by teachers who already spend their day in AURAK EUMS,
Blackboard, Microsoft 365 and Google Workspace. Nothing here is invented: every
pattern below was taken from a product those teachers already know, so the
screens behave the way they expect (Jakob's law). This file records what was
borrowed and where it is used, so the next person can check the original rather
than guess at the intent.

Checked on 7 November 2026.

---

## Microsoft Forms — quizzes

<https://support.microsoft.com/en-us/office/a082a018-24a1-48c1-b176-4b3616cdc83d>

**What was taken**

1. *Add a question by picking its type.* Forms offers one **Add new** button and
   then a short list of types (Choice, Text, Rating, Date), with the rest behind
   **More question types**. "Create a quiz or exam" step 3 is the same idea
   turned into a table: one row per type a teacher is likely to want, the rare
   ones left out rather than hidden in a menu, and a number stepper instead of
   adding questions one at a time.
2. *Points live on the question.* Forms puts a **Points** box on each question.
   Our step 3 puts a points box next to each type, and the quiz review page
   keeps a points box on each question card.
3. *The correct answer is marked on the option itself.* Forms marks it with a
   check mark beside the answer. Our review page shows the correct option
   marked in place on the question card, not in a separate key section.
4. *Review by scrolling the paper.* Forms' **Preview** shows the quiz as a
   respondent sees it. Our review page shows the question paper, with the
   teacher's actions attached to each card.

**What was deliberately not taken:** Forms' Copilot panel ("Draft with Copilot",
**Keep it** / **Regenerate**) sits beside the quiz as a separate assistant. In
EduForge the drafting *is* the flow, and every draft needs a named approval, so
there is no separate assistant panel to dismiss.

## Canvas — question groups linked to a question bank

<https://community.instructure.com/en/kb/articles/661000-how-do-i-create-a-quiz-with-a-question-group-linked-to-a-question-bank>

**What was taken**

1. *Say how many and how much, not which.* Canvas' **New Question Group** asks
   for a name, "how many questions you want Canvas to randomly select from the
   group" and "the number of points assigned to each question". Step 3 of our
   flow is exactly that shape — a count and a points value per question type —
   rather than a list of individual questions to tick.
2. *A bank you draw from, separate from the paper.* Canvas separates the
   question bank from the quiz that references it. We keep the same split: the
   **Question bank** page is for browsing and reusing approved questions, and a
   quiz draws from it (or has new questions written for it).
3. *Save before publish.* Canvas distinguishes **Save** from **Save & Publish**.
   Our paper is a draft until "Approve this paper", and only an approved paper
   can be downloaded or sent to Blackboard.

**What was deliberately not taken:** Canvas pulls questions at random *per
student*. Our teachers need to see and approve every question before it is
used, so a paper is fixed once built; parallel versions are made explicitly.

## GOV.UK Design System — one thing per page, and error messages

<https://design-system.service.gov.uk/patterns/question-pages/> and
<https://designnotes.blog.gov.uk/2015/07/03/one-thing-per-page/>

**What was taken**

1. *One thing per step.* "Create a quiz or exam" is four short steps with Back
   and Continue, instead of one long form. Each step asks one question and
   names it as a heading: "What are you making?", "What should it cover?",
   "How many of each type?", "Ready to write them".
2. *Plain language, no jargon.* Every rule id, JSON pointer and internal term
   was replaced with the words a teacher uses. The glossary lives in
   `PLAIN_TITLES` in `backend/app/validation/rules.py` and in the UI copy.
3. *Error messages say what happened, why it matters and what to do.* "Confirm
   the syllabus for this term before writing questions." rather than a status
   code. Nielsen Norman's error-message guidance
   (<https://www.nngroup.com/articles/error-message-guidelines/>) says the same:
   be explicit, human, and constructive.

## Nielsen Norman Group — progressive disclosure

<https://www.nngroup.com/articles/progressive-disclosure/>

**What was taken:** the uncommon controls are one click away, never gone. Bloom
level, model notes and the avoid-list sit under **Advanced options** in the quiz
flow; blueprint numbers, usage history, the AI-solvability check, the shared
bank and QTI sit under **Advanced** on the quiz review page; rule ids, the
technical message and the raw JSON pointer sit under **Details** on a thing to
check.

## Stripe Dashboard — KPI cards and tables

**What was taken:** a row of four cards at the top of the home screen, each one
number plus a one-line explanation of what it counts and a link to the filtered
list behind it; below them, a plain table with a quiet header row, dividers and
tabular numbers. The first card is a solid brand-coloured card so the eye has
one place to land.

## Linear and Notion — a calm layout

**What was taken:** a white sidebar with a crimson pill on the active item
rather than a coloured chrome; generous white space on an 8 px grid; one
typeface; quiet 1 px borders with a very soft shadow instead of heavy cards; and
the rule that a screen has exactly one filled button.

## Blackboard Ultra and AURAK EUMS

**What was taken:** the shape teachers already navigate — a fixed left sidebar
with course-level links appearing under the open course, a breadcrumb trail
above the page title, the page title top left and the main action top right.
EUMS is also why the brand crimson is used for the active item and the primary
action and nothing else: in EUMS, red is the institution, not a warning.

---

## Colour

The crimson and gold were sampled from the AURAK logo at
<https://www.aurak.ac.ae> (the mark on the home page, read pixel by pixel):
the dominant red is `#C41F32` and the seal gold is around `#CCA74B`. We use
`#C41F32` as the brand colour (white text on it is 5.9:1, which passes AA) with
`#A51C30` as the hover shade, and `#C9A227` as the accent, which is only ever a
fill — never text on white, where it is 2.4:1.
