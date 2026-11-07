# Real sample syllabi (not committed)

Put the vetted AURAK sample syllabi here (PDF or DOCX). They contain faculty
names and emails, so `.gitignore` keeps everything in this folder except this
README out of git.

The five files the acceptance tests look for (HANDOFF §9), matched by course
code anywhere in the file name:

| Course | Format | Term |
|---|---|---|
| CSCI 372 Compiler Design | PDF | Spring 2026 |
| CSAI 351 Data Science | DOCX | Fall 2026 |
| CENG 411 Software Engineering | DOCX | Fall 2026 |
| CENG 401 Network Servers & Architecture | PDF | Fall 2026 |
| STAT 100 Intro Probability & Statistics | PDF | Fall 2026 |

Then run `uv run pytest tests/test_acceptance_real.py -v` from `backend/`.
