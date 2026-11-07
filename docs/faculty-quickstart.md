# EduForge: a quick start for teachers

EduForge turns the syllabus your department approved into a checked course
record. From that record it writes draft questions, exercises, lesson plans and
other materials, and it can suggest marks for a class.

**Nothing it writes is used until you approve it**, and it never changes your
syllabus on its own.

You do not need to read this before starting. Every screen says what it is and
what to do next. This is here for when you want the whole route in one place.

---

## The route, in short

**Dashboard → Upload a syllabus → Things to check → Confirm syllabus for this
term → Create a quiz or exam → review and approve → download the paper and the
key → Marking.**

---

## 1. Upload your syllabus

On **My courses**, press **Upload a syllabus** and pick the PDF or Word file
your department approved.

EduForge reads the course code and title, the term, the learning outcomes, the
assessments and their weights, the weekly plan and the programme-outcome
appendix.

One syllabus per course and term. If you upload a newer file later, the old one
is kept and marked as replaced.

## 2. Settle the things to check

The **Things to check** panel lists what did not add up: weights that do not
total 100%, an assessment table that disagrees with the weekly plan, two
assessments with the same name, a quiz on a day the class does not meet.

Each one is a card with a plain sentence. For each, do one of two things:

- **Fix** — opens the choices EduForge has prepared, as a list you pick from
  ("Use 25% everywhere", "Move it back to Tuesday 22 September"). The last
  option is always **Set it myself**, which opens the full form.
- **Keep as it is** — for when the syllabus is right as written. A short note
  on why is optional, and it is kept with the record.

Nothing is fixed automatically. The progress bar at the top of the panel counts
down as you settle them.

To see where a value came from, press **Source** next to it. You get the page
and the line of your own file.

Every change you make is written to **Changes you made**, in plain English, and
you can export that log.

## 3. Confirm the syllabus for this term

When nothing must-fix is left, press **Confirm syllabus for this term**.

Questions are only written from a syllabus you have confirmed. To change it
afterwards, start a new version; the old one stays as the record of what you
confirmed.

If you confirmed the same course in an earlier term, EduForge offers to carry
over the things you settled then.

## 4. Add your slides and notes (worth doing)

Under **Slides and materials**, add your slides, notes and past papers, tagged
by week.

Drafts are then written from *your* material, and each one says **Based on your
slides: <file name>**. Without them, drafts say **Written from the syllabus
only (no slides added)** — still usable, but in EduForge's wording rather than
yours.

- **Published textbooks** are only used if you confirm the university's licence
  allows it.
- **Past papers** never leave the university's own systems.

## 5. Create a quiz or exam

Press **Create a quiz or exam**. Four steps, one question each:

1. **What are you making?** Pick a row from your syllabus — Quiz 2, Midterm,
   Final — and the weeks and outcomes it covers are filled in for you. Or pick
   **Practice questions**, which is not graded.
2. **What should it cover?** Tick the weeks and the learning outcomes. Change
   them if you want something narrower.
3. **How many of each type?** Set how many multiple-choice, short-answer,
   worked-problem, code or case-study questions, and what each is worth. The
   running total tells you how many questions, how many points and roughly how
   long it will take a student to sit.
4. **Write the questions.** One press, and the whole paper is written.

Blueprints, re-using questions from the bank and parallel versions for
different sections are still there, under **Advanced options** on step 3.

## 6. Review and approve

Every question arrives as a draft, on its own card, with the correct answer
marked on the option itself and its own checks:

- Does it match the learning outcome, at the right level of thinking?
- Does the answer key hold up when the question is solved again, independently?
- Does any code pass its hidden tests?
- Is it nearly the same as another question you already have?

A question that fails a required check cannot be approved until you edit it.
The card says why, in a sentence.

For each one: **Approve**, **Edit** (which sends it back for its checks to run
again) or **Replace** (write another one, saying what should change).

When every question is approved, press **Approve this paper**.

## 7. Download the paper and the key

You always get **two separate files**:

- the **question paper** — numbered questions, options as A./B./C./D., a name
  and student ID line, no answers and no outcome or week tags;
- the **answer key** — the correct answer, why it is correct, why each wrong
  option is wrong, and the tags.

Both download as Word or PDF. There is also a QTI file to import into
Blackboard.

Treat question banks as test material under the AURAK Honor Code.

## 8. Marking (when your department has switched it on)

The page has four steps across the top.

**Before you start:** confirm the grading scale. It is read from your syllabus,
and you are told if it differs from your other syllabuses this term.

1. **Add your students.** A class list as a CSV with a student ID, a name and
   an email. Names are stored encrypted; the rest of EduForge only ever sees a
   code name such as `S-7KQ2MD`. Each time you reveal who is who, that is
   recorded.
2. **Add their answers.** Either a CSV of typed answers with columns Q1, Q2, …
   numbered as on the paper, or one PDF, Word or text file per student with the
   student ID in the file name, or a ZIP of those. Names, ids, emails and phone
   numbers are removed from the answers before anything else happens.
3. **Check the suggested marks.** Multiple-choice and numeric answers are
   marked straight from your key. Code is run against the hidden tests. Written
   answers get a suggested level per criterion, quoting the student's own
   words. Amber cells are the ones that need you: low confidence, no evidence,
   or no suggestion at all.

   **You confirm every mark.** "Confirm all answer-key marks" handles the
   objective ones in one press. If you move a confident suggestion by more than
   one level, give a short reason.

   Approve, edit or drop the feedback drafts. Only feedback you approved is
   sent.
4. **Release the marks.** You get a Blackboard Grade Center CSV, a marks sheet
   with letter grades, and a feedback PDF per student. Release stays blocked
   until every mark is confirmed and the scale is confirmed.

Afterwards, record any appeal on the student's page. The decision and the
re-mark are kept in the history, and a released mark changes only that way.

**Want to see it before you trust it with a class?** On the **Marking** page there
is **Try it with a sample class of 30 students**: thirty invented students with
invented answers, marked the same way as a real class.

## 9. Blackboard (when IT has connected it)

1. Open **Blackboard** from your course and press **Connect Blackboard**. You
   sign in to Blackboard yourself, and EduForge acts as you.
2. **Link** one of your Blackboard courses, with the class if you are marking.
   The course code and term must match your syllabus; a course that does not
   match is refused.
3. **Push** an approved paper. This creates its Grade Center column. Import the
   paper's QTI file into Blackboard as a test or pool yourself — Blackboard
   does not let that step happen automatically.
4. **Pull submissions** to bring the students' answers into Marking,
   anonymised.
5. Once every mark is confirmed, **Preview grade upload**, then **Write
   confirmed grades**. A grade you changed in Blackboard yourself is skipped
   unless you tick *overwrite*. Running it again writes only what is missing.

---

*Questions? Contact the EduForge team.*
