# EduForge: faculty quick-start

EduForge turns your vetted syllabus into a checked course record. From that record it drafts questions, exercises, lesson plans and other materials. **Nothing the AI writes is used until you approve it.**

## 1. Upload your syllabus

1. Sign in with your university account.
2. On **My courses**, drop your **vetted** syllabus (PDF or DOCX).

EduForge reads the course, term, CLOs, assessments, weekly plan and the PLO appendix from the file.

## 2. Settle the flags, then lock

The right-hand panel lists what the checker found, such as weights that don't add up, a CLO matrix that disagrees with the schedule, or a quiz on a day the class doesn't meet. For each flag, do one of these:

- **Fix the value.** Hover over a field and click **Edit**. Where the flag offers **Choose a value**, one click applies the fix. The flag clears itself once the problem is gone.
- **Accept as is.** Use this if the syllabus is right as written; a note is optional.

To see where a value came from, click **Source** next to it, or a flag's grey location button. You'll see the page and row of your file.

Every change is logged against the uploaded file. Export the log from the **Edit log** tab.

When nothing is left to settle, click **Lock working version**. Drafts are only made from a locked version. To change a locked version later, use **Create new version**.

If you locked this course in an earlier term, EduForge offers to carry over the flags you settled then.

## 3. Add your course materials (recommended)

Under **Course materials**, upload slides, notes and past exams, tagged by week. Drafts are then built from *your* material, and each draft shows **grounded**. Without materials, drafts come from the syllabus alone and show **ungrounded**.

- **Commercial textbooks** are only used if you confirm the university's licence allows it.
- **Past exams** never leave the university's own systems.

## 4. Draft, review, approve

In **Draft Studio**, pick the item type, CLOs, weeks and how many. Every draft arrives with quality checks:

- Is it aligned with the CLO and the right Bloom level?
- Does the answer key re-check?
- Does any code pass its tests?
- Is it a near-duplicate of another item?

**Required** checks must pass before you can approve.

For each draft, do one of these:

- **Approve** it.
- **Edit** it, which sends it back to review.
- **Reject** it.
- **Regenerate with notes**, saying what should change.

## 5. Export

**Export DOCX/PDF** includes approved items only. Tick **with answer key** for your copy and leave it unticked for students.

Treat question banks as test material under the AURAK Honor Code.

## 6. Build a quiz or exam

Open **Assessment Builder** from a locked course, then pick a row of your syllabus, such as "Midterm".

1. Adjust the blueprint if you need to: weeks, CLO shares, item counts, time and points.
2. **Build** one form, or parallel versions for different sections.
3. The builder uses only approved items. It lists exactly what's missing, and it skips items used in recent terms.
4. Reorder items, swap them or change points. Then **Approve form**.
5. Export as DOCX, PDF or QTI, which you can import into Blackboard. Draft forms don't export.

## 7. Grading Assist (only when your department has switched it on)

1. **Confirm the grading scale.** It is read from your syllabus, and you are told if it differs from other syllabi this term.
2. **Add a section** and upload its roster: a CSV with Student ID, Name and Email. Students then appear under pseudonyms such as `S-7KQ2MD`.
3. **Upload submissions** for an approved form, in one of these shapes:
   - a CSV of typed answers, with columns Q1, Q2, … numbered as on the form;
   - one PDF, DOCX or TXT file per student, with the student ID in the file name;
   - a ZIP of those files.

   Names, IDs and emails are removed from answers before anything else happens.
4. Review the suggestions:
   - Multiple choice and numeric answers are marked from your answer key.
   - Code is run against the hidden tests.
   - Open answers get a suggested level per criterion, quoting the student's own words.

   Amber cells need you: low confidence, no evidence, or no suggestion.
5. **You confirm every mark.** "Confirm all answer-key marks" handles the objective ones. If you move a confident suggestion by more than one level, give a short reason.
6. Approve, edit or drop the feedback drafts. Only approved feedback is released.
7. **Release grades.** You get a Blackboard Grade Center CSV, a marks sheet with letters, and a feedback PDF per student. Release stays blocked until every mark is confirmed.
8. After release, record any appeal on the student's page. The decision and the re-mark are kept in the history.

## 8. Blackboard (only when IT has connected it)

1. Open **Blackboard** from your course and **Connect Blackboard**. You sign in to Blackboard yourself, and the tool acts as you.
2. **Link** one of your Blackboard courses, with the section if you're grading. The course code and term must match your syllabus; a mismatched course is refused.
3. **Push** an approved form. This creates its Grade Center column. Import the form's QTI export (Assessment Builder) into Blackboard as a test or pool, because Blackboard doesn't allow that step automatically.
4. **Pull submissions** to bring the students' answers into Grading Assist, anonymised.
5. Once every mark is confirmed, **Preview grade upload**, then **Write confirmed grades**. A grade you changed in Blackboard is skipped unless you tick *overwrite*. Running it again writes only what's missing.

*Questions? Contact the EduForge team.*
