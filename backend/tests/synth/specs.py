"""Synthetic stand-ins for the five AURAK sample syllabi (HANDOFF §9).

The real files are not in the repo. These specs rebuild each course in the
AURAK template layout and plant exactly the issues §9 says the validator must
catch. ``EXPECTED`` lists those issues so the acceptance tests can assert them.

Names and contacts are placeholders. ABET outcome wording is the public
ABET CAC/EAC criteria text.
"""

from __future__ import annotations

CS_PLOS = [
    "Analyze a complex computing problem and apply principles of computing and other relevant disciplines to identify solutions.",
    "Design, implement, and evaluate a computing-based solution to meet a given set of computing requirements in the context of the program's discipline.",
    "Communicate effectively in a variety of professional contexts.",
    "Recognize professional responsibilities and make informed judgments in computing practice based on legal and ethical principles.",
    "Function effectively as a member or leader of a team engaged in activities appropriate to the program's discipline.",
    "Apply computer science theory and software development fundamentals to produce computing-based solutions.",
]
CE_PLOS = [
    "An ability to identify, formulate, and solve complex engineering problems by applying principles of engineering, science, and mathematics.",
    "An ability to apply engineering design to produce solutions that meet specified needs with consideration of public health, safety, and welfare.",
    "An ability to communicate effectively with a range of audiences.",
    "An ability to recognize ethical and professional responsibilities in engineering situations and make informed judgments.",
    "An ability to function effectively on a team whose members together provide leadership and meet objectives.",
    "An ability to develop and conduct appropriate experimentation, analyze and interpret data, and use engineering judgment.",
    "An ability to acquire and apply new knowledge as needed, using appropriate learning strategies.",
]
AI_PLOS = CS_PLOS[:5] + [
    "Apply artificial intelligence theory and techniques to design and build intelligent systems.",
    "Apply data analytics and machine learning methods responsibly to solve real-world problems.",
]
AIDS_PLOS = CS_PLOS[:5] + [
    "Apply data science and AI methods to extract knowledge from large and complex datasets.",
    "Develop AI and data science solutions that consider ethical, legal and societal impacts.",
]
GE_PLOS = [
    "Communicate ideas clearly and effectively in written and oral forms.",
    "Apply quantitative reasoning to analyze and solve problems.",
    "Think critically and evaluate information from multiple sources.",
    "Demonstrate awareness of ethical, social and cultural issues.",
]

POLICIES = [
    ("Attendance Policy", "Students are expected to attend all classes. Absence above the allowed limit leads to a WF grade."),
    ("Academic Integrity", "All work must follow the AURAK Honor Code. Plagiarism and cheating are reported."),
    ("Students with Disabilities", "Students who need accommodations should contact the Accessibility office."),
]

GRADING_FALL = [["Grade", "Range"], ["A", "90-100"], ["B", "80-89"], ["C", "70-79"], ["D", "60-69"], ["F", "0-59"]]
GRADING_SPRING = [["Grade", "Range"], ["A", "95-100"], ["A-", "90-94"], ["B+", "87-89"], ["B", "83-86"],
                  ["C", "73-76"], ["D", "60-66"], ["F", "0-59"]]


def program_block(name: str, plos: list[str], mapping: dict[int, dict[int, str]], addressed: list[int],
                  fused: bool = False) -> list:
    """APPENDIX block: PLO list, CLO→PLO mapping (H/M/L), ABET 'addressed' table."""
    n = len(plos)
    items: list = [("para", f"Program Learning Outcomes (PLOs) for the BS in {name}")]
    items.append(("table", [["PLO", "Description"]] + [[f"PLO {i}", t] for i, t in enumerate(plos, 1)]))
    items.append(("para", f"Mapping of CLOs to PLOs – BS in {name}"))
    rows = [["CLOs"] + [f"PLO {i}" for i in range(1, n + 1)]]
    for clo in sorted(mapping):
        rows.append([f"CLO {clo}"] + [mapping[clo].get(p, "") for p in range(1, n + 1)])
    abet = [["ABET Student Outcomes"] + [str(i) for i in range(1, n + 1)],
            ["Addressed in course"] + ["X" if i in addressed else "" for i in range(1, n + 1)]]
    if fused:
        # CENG 411: the AI&DS mapping table and ABET table arrive as one malformed table.
        items.append(("table", rows + abet))
    else:
        items.append(("table", rows))
        items.append(("para", f"ABET Student Outcomes addressed in the course – BS in {name}"))
        items.append(("table", abet))
    return items


def build(c: dict) -> list:
    """Course dict -> ordered document items in AURAK template order."""
    items: list = [
        ("title", "American University of Ras Al Khaimah"),
        ("para", "Course Syllabus"),
        ("table", [
            ["Course Title", c["title"]],
            ["Course Code", c["code"]],
            ["Credit Hours", "3"],
            ["Semester and Academic Year", c["term"]],
            ["Class Timing(s)", c["timing"]],
            ["Method(s) of Instruction", "Face-to-face lectures and labs"],
            ["Prerequisite course(s)", c["prereq"]],
            ["Faculty Name", "Dr. Placeholder Instructor"],
            ["Contact Information and Office Hours", "instructor@example.edu, Office B-101, Mon 10:00-12:00"],
        ]),
        ("heading", "Course Description"), ("para", c["description"]),
        ("heading", "Additional Information about the Course"), ("para", c["additional"]),
        ("heading", "Course Textbooks and Materials"), *[("para", t) for t in c["textbooks"]],
        ("heading", "Other Resources"), ("para", c.get("other", "Lecture slides and notes on the LMS.")),
        ("heading", "Web Resources"), ("para", c.get("web", "https://www.example.edu/course")),
        ("heading", "Course Learning Outcomes (CLOs)"),
        ("table", [["CLO", "Description"]] + [[f"CLO {i}", t] for i, t in enumerate(c["clos"], 1)]),
        ("heading", "Assessment Activities"),
        ("table", c["assessment_table"]),
        ("heading", "Grading Scale"), ("table", c.get("grading", GRADING_FALL)),
        ("heading", "Weekly Course Information"),
    ]
    header = ["Week", "Topic", "Required Readings", "Assignment/Assessment (weight & due date)",
              "Mapping of CLOs to Assessments"]
    for ti, tbl in enumerate(c["weekly_tables"]):
        if ti > 0 and c.get("weekly_pagebreak"):
            items.append(("pagebreak",))
        rows = ([header] if (ti == 0 or c.get("repeat_weekly_header")) else []) + tbl
        items.append(("table", rows, {"grid": not c.get("weekly_gridless")}))
    for h, p in POLICIES:
        items += [("heading", h), ("para", p)]
    items.append(("heading", "APPENDIX"))
    for prog in c["programs"]:
        items += program_block(**prog)
    return items


def W(week, topic, readings="", assessment="", clos=""):
    return [str(week), topic, readings, assessment, clos]


def matrix(names: list[str], weights: list[str], clo_marks: dict[int, list[str]], n_clos: int) -> list[list[str]]:
    """Horizontal weight table + CLO × assessment X matrix."""
    rows = [["Assessment"] + names + ["Total"], ["Weight"] + weights + ["100%"]]
    for clo in range(1, n_clos + 1):
        marked = clo_marks.get(clo, [])
        rows.append([f"CLO {clo}"] + ["X" if n in marked else "" for n in names] + [""])
    return rows


# --------------------------------------------------------------------------- #
# CSCI 372 Compiler Design — PDF, Spring 2026, no internal issues
# --------------------------------------------------------------------------- #
CSCI372 = dict(
    code="CSCI 372", title="Compiler Design", term="Spring 2026",
    timing="Tue/Thu 11:30 AM - 12:45 PM", prereq="CSCI 260 Theory of Computation",
    description=("This course covers the theory and practice of compiler construction: lexical analysis with "
                 "regular expressions and finite automata, parsing of context-free grammars, syntax-directed "
                 "translation, semantic analysis and type checking, intermediate code generation and code optimization."),
    additional=("Students build a working compiler front end for a small language in stages, from the lexical "
                "analyzer and parser to intermediate code generation."),
    textbooks=["Aho, Lam, Sethi, Ullman. Compilers: Principles, Techniques, and Tools, 2nd ed. ISBN 978-0321486813"],
    grading=GRADING_SPRING,
    clos=[
        "Describe the phases of a compiler and implement lexical analysis using regular expressions and finite automata.",
        "Construct top-down and bottom-up parsers (LL(1), LR, LALR) for context-free grammars.",
        "Write syntax-directed translation schemes and perform semantic analysis including type checking.",
        "Generate intermediate code and apply code optimization techniques.",
    ],
    assessment_table=matrix(
        ["Quizzes", "Homework Assignments", "Midterm Exam", "Project", "Final Exam"],
        ["10%", "30%", "25%", "10%", "25%"],
        {1: ["Quizzes", "Homework Assignments", "Midterm Exam", "Final Exam"],
         2: ["Homework Assignments", "Midterm Exam", "Final Exam"],
         3: ["Quizzes", "Homework Assignments", "Final Exam"],
         4: ["Quizzes", "Project", "Final Exam"]}, 4),
    weekly_pagebreak=True,
    weekly_tables=[
        [
            W(1, "Introduction to compilers; Phases of a compiler", "Ch. 1"),
            W(2, "Lexical analysis; Regular expressions", "Ch. 3.1-3.3"),
            W(3, "Finite automata; Lexical analyzer generators", "Ch. 3.4-3.9"),
            W(4, "Context-free grammars", "Ch. 4.1-4.3", "Quiz 1 (5%) – 10 February 2026", "CLO 1"),
            W(5, "Top-down parsing; LL(1) parsers", "Ch. 4.4", "HW1 (10%) Due: 19-Feb", "CLO 1, 2"),
            W(6, "Bottom-up parsing; LR and LALR parsers", "Ch. 4.5-4.7"),
            W(7, "Parser generators", "Ch. 4.9", "HW2 (10%) Due Week 7", "CLO 2"),
            W(8, "Midterm review", "", "Midterm Exam (25%) – 12 March 2026", "CLO 1, 2"),
            W(9, "Syntax-directed translation schemes", "Ch. 5"),
            W(10, "Semantic analysis; Type checking", "Ch. 6.5", "HW3 (10%) Due: 02-04-2026", "CLO 3"),
            W(11, "Intermediate code generation; Three-address code", "Ch. 6.1-6.4"),
            W(12, "Run-time environments", "Ch. 7"),
            W(13, "Code generation", "Ch. 8", "Quiz 2 (5%) – 16 April 2026", "CLO 3, 4"),
        ],
        [   # continues on the next page without a header row
            W(14, "Code optimization", "Ch. 9", "Project (10%) Due: 30-Apr", "CLO 4"),
            W(15, "Data-flow analysis", "Ch. 9.2"),
            ["", "Loop optimizations", "Ch. 9.6", "", ""],  # row continued across the page break
            W(16, "Final examination", "", "Final Exam (25%) – TBA", "CLO 1, 2, 3, 4"),
        ],
    ],
    programs=[dict(name="Computer Science", plos=CS_PLOS,
                   mapping={1: {1: "H", 6: "M"}, 2: {1: "H", 2: "M"}, 3: {2: "H", 6: "L"}, 4: {1: "M", 2: "H"}},
                   addressed=[1, 2, 6])],
)

# --------------------------------------------------------------------------- #
# CSAI 351 Data Science — DOCX, Fall 2026
#   V4: two different 'Quiz #1' (10% wk5, 5% wk12)
#   V7: ABET marks PLO 6 addressed, no CLO maps to PLO 6
#   weeks 13–16 in a separate table
# --------------------------------------------------------------------------- #
CSAI351 = dict(
    code="CSAI 351", title="Data Science", term="Fall 2026",
    timing="Tuesday & Thursday 1:30 - 2:45 PM", prereq="STAT 100 and CSCI 112",
    description=("This course introduces the data science workflow: data wrangling and exploratory analysis in "
                 "Python, machine learning models for classification and regression, model evaluation, and "
                 "communicating insights through visualization."),
    additional=("Labs use Python, pandas and scikit-learn on public datasets; students complete a team data "
                "science project with a written report and visualization."),
    textbooks=["Grus, J. Data Science from Scratch, 2nd ed. O'Reilly. ISBN 978-1492041139"],
    clos=[
        "Apply data wrangling and exploratory data analysis techniques using Python.",
        "Build and evaluate machine learning models for classification and regression.",
        "Communicate data-driven insights through visualization and written reports.",
    ],
    assessment_table=matrix(
        ["Quizzes", "Assignments", "Midterm", "Project", "Final"],
        ["15%", "20%", "15%", "25%", "25%"],
        {1: ["Quizzes", "Assignments", "Midterm", "Final"],
         2: ["Quizzes", "Assignments", "Midterm", "Project", "Final"],
         3: ["Project", "Final"]}, 3),
    repeat_weekly_header=True,
    weekly_tables=[
        [
            W(1, "Introduction to data science; Python for data analysis", "Ch. 1-2"),
            W(2, "Data wrangling with pandas", "Ch. 10"),
            W(3, "Exploratory data analysis", "Ch. 5"),
            W(4, "Data visualization", "Ch. 3"),
            W(5, "Probability and statistics review", "Ch. 6-7", "Quiz #1 (10%) Due: W5", "CLO 1"),
            W(6, "Introduction to machine learning", "Ch. 11"),
            W(7, "Linear regression", "Ch. 14", "Assignment 1 (10%) Due Week 7", "CLO 1"),
            W(8, "Midterm review", "", "Midterm (15%) – 22-10-2026", "CLO 1, 2"),
            W(9, "Classification models: decision trees and k-NN", "Ch. 12, 17"),
            W(10, "Model evaluation and cross-validation", "Ch. 11", "Assignment 2 (10%) Due: 12-Nov", "CLO 2"),
            W(11, "Regression models; Regularization", "Ch. 15"),
            W(12, "Clustering", "Ch. 20", "Quiz #1 (5%) Due: W12", "CLO 2"),
        ],
        [   # weeks 13–16 sit in a separate table
            W(13, "Dimensionality reduction", "Ch. 10.4"),
            W(14, "Communicating results: visualization and reporting", "", "Project (25%) Due: 3 December 2026",
              "CLO 2, 3"),
            W(15, "Project presentations"),
            W(16, "Final examination", "", "Final (25%) – TBA", "CLO 1, 2, 3"),
        ],
    ],
    programs=[dict(name="AI", plos=AI_PLOS,
                   mapping={1: {1: "H", 2: "M"}, 2: {1: "M", 2: "H", 7: "M"}, 3: {3: "H"}},
                   addressed=[1, 2, 3, 6, 7])],
)

# --------------------------------------------------------------------------- #
# CENG 411 Software Engineering — DOCX, Fall 2026, three programs
#   V2: Midterm 25% (table) vs 20% (schedule)
#   V3: HW1–HW4 5% each, no HW category; IBM Certification and Other
#       Activities (10% each) missing from the schedule
#   EX: AI&DS mapping table fused with the ABET table
#   V7 (info): CLO5→PLO4 Medium for CE, High for CS and AI&DS
# --------------------------------------------------------------------------- #
CENG411 = dict(
    code="CENG 411", title="Software Engineering", term="Fall 2026",
    timing="Tue/Thu 9:00 - 10:15 AM", prereq="CSCI 211 Data Structures",
    description=("This course covers software engineering processes and agile practices, requirements "
                 "elicitation and specification, software architecture and UML modeling, design patterns, "
                 "software testing and quality assurance, and professional ethics in team projects."),
    additional=("Students work in teams on a semester-long software project using Scrum, and may earn an IBM "
                "agile software engineering certification."),
    textbooks=["Sommerville, I. Software Engineering, 10th ed. Pearson. ISBN 978-0133943030"],
    clos=[
        "Explain software process models and apply agile practices to plan a software project.",
        "Elicit, analyze and specify software requirements using use-case and user-story techniques.",
        "Design software architectures and model systems using UML diagrams.",
        "Apply software testing techniques and quality assurance practices.",
        "Communicate effectively in written and oral form and work in teams following professional and ethical responsibilities.",
    ],
    assessment_table=matrix(
        ["Midterm", "Final", "Project", "IBM Certification", "Other Activities"],
        ["25%", "30%", "25%", "10%", "10%"],
        {1: ["Midterm", "Final", "Project"], 2: ["Midterm", "Final", "Project"], 3: ["Midterm", "Final", "Project"],
         4: ["Final", "IBM Certification"], 5: ["Project", "Other Activities"]}, 5),
    weekly_tables=[[
        W(1, "Introduction to software engineering; Software process models", "Ch. 1-2"),
        W(2, "Agile development: Scrum and project planning", "Ch. 3"),
        W(3, "Requirements engineering: elicitation", "Ch. 4", "HW1 (5%) Due Week 3", "CLO 1, 2"),
        W(4, "Use cases and user stories; Requirements specification", "Ch. 4"),
        W(5, "Software architecture styles", "Ch. 6"),
        W(6, "UML modeling: class and sequence diagrams", "Ch. 5", "HW2 (5%) Due Week 6", "CLO 2, 3"),
        W(7, "Design patterns", "Ch. 7"),
        W(8, "Midterm review", "", "Midterm Exam (20%) – 15-Oct", "CLO 1, 2, 3"),
        W(9, "Software testing: unit and integration testing", "Ch. 8"),
        W(10, "Test-driven development", "Ch. 8", "HW3 (5%) Due Week 10", "CLO 4"),
        W(11, "Quality assurance and code reviews", "Ch. 24"),
        W(12, "Software maintenance and evolution", "Ch. 9", "HW4 (5%) Due Week 12", "CLO 4"),
        W(13, "Professional ethics and teamwork", "Ch. 1.2"),
        W(14, "Project presentations", "", "Project (25%) Due: 3 December 2026", "CLO 1, 2, 3, 5"),
        W(15, "Course review"),
        W(16, "Final examination", "", "Final Exam (30%) – TBA", "CLO 1, 2, 3, 4"),
    ]],
    programs=[
        dict(name="Computer Engineering", plos=CE_PLOS,
             mapping={1: {1: "M", 7: "L"}, 2: {1: "H", 2: "M"}, 3: {2: "H"}, 4: {6: "H"},
                      5: {3: "H", 4: "M", 5: "H"}},
             addressed=[1, 2, 3, 4, 5, 6, 7]),
        dict(name="Computer Science", plos=CS_PLOS,
             mapping={1: {1: "M"}, 2: {1: "H", 2: "M"}, 3: {2: "H", 6: "M"}, 4: {2: "M", 6: "H"},
                      5: {3: "H", 4: "H", 5: "H"}},
             addressed=[1, 2, 3, 4, 5, 6]),
        dict(name="AI and Data Science", plos=AIDS_PLOS, fused=True,
             mapping={1: {1: "M"}, 2: {1: "H", 2: "M"}, 3: {2: "H", 6: "M"}, 4: {2: "M", 6: "H"},
                      5: {3: "H", 4: "H", 5: "H"}},
             addressed=[1, 2, 3, 4, 5, 6]),
    ],
)

# --------------------------------------------------------------------------- #
# CENG 401 Network Servers & Architecture — PDF, Fall 2026
#   V11: additional info is about embedded systems design
#   V6:  Quiz #2, AWS Lab 2, AWS Lab 4 have no CLO; week 12 maps CLOs with
#        no assessment (row shift)
#   V10: template text left in
#   week 5 cell holds two assessments sharing one CLO list
# --------------------------------------------------------------------------- #
CENG401 = dict(
    code="CENG 401", title="Network Servers & Architecture", term="Fall 2026",
    timing="Tue/Thu 2:00 - 3:15 PM", prereq="CENG 301 Computer Networks",
    description=("This course covers the architecture, configuration and administration of network servers: "
                 "client-server protocols, web, DNS, mail and directory servers on Linux, virtualized and cloud "
                 "servers on AWS, and securing network services with firewalls and TLS."),
    additional=("This course provides hands-on experience in embedded systems design using microcontrollers, "
                "real-time operating systems, sensors and actuators. Students write firmware in C for ARM Cortex-M "
                "boards and interface peripherals such as GPIO, timers, ADC and UART."),
    textbooks=["Kurose, J., Ross, K. Computer Networking: A Top-Down Approach, 8th ed. ISBN 978-0135928615"],
    other="(See Syllabus Guide for additional information that should be added here)",
    clos=[
        "Explain the architecture and protocols of client-server network services.",
        "Configure and administer web, DNS, mail and directory servers on Linux.",
        "Deploy and manage virtualized servers and cloud services on AWS.",
        "Secure network servers using firewalls, TLS and access control.",
    ],
    assessment_table=matrix(
        ["Quizzes", "AWS Labs", "Midterm", "Project", "Final"],
        ["10%", "20%", "20%", "20%", "30%"],
        {1: ["Quizzes", "AWS Labs", "Midterm", "Final"], 2: ["Quizzes", "AWS Labs", "Midterm", "Project", "Final"],
         3: ["AWS Labs", "Project", "Final"], 4: ["Project", "Final"]}, 4),
    weekly_tables=[[
        W(1, "Introduction to network architecture and the client-server model", "Ch. 2.1"),
        W(2, "TCP/IP protocols and network services", "Ch. 2.2-2.3"),
        W(3, "Linux server administration", "Notes"),
        W(4, "DNS servers and configuration", "Ch. 2.4"),
        W(5, "Web and mail servers", "Ch. 2.2", "Quiz #1 (5%) – 1-Oct\nAWS Lab 1 (5%) Due: 2-Oct", "CLO 1, 2"),
        W(6, "Directory services with LDAP", "Notes"),
        W(7, "Virtualization and containers", "Notes", "AWS Lab 2 (5%) Due Week 7", ""),
        W(8, "Midterm review", "", "Midterm (20%) – 15-Oct", "CLO 1, 2"),
        W(9, "Cloud computing with AWS", "AWS docs"),
        W(10, "Deploying servers on AWS EC2", "AWS docs", "AWS Lab 3 (5%) Due Week 10", "CLO 3"),
        W(11, "Network security and firewalls", "Ch. 8.9", "Quiz #2 (5%) – 12-Nov", ""),
        W(12, "Load balancing and high availability", "Notes", "", "CLO 3, 4"),
        W(13, "TLS and access control", "Ch. 8.6", "AWS Lab 4 (5%) Due Week 13", ""),
        W(14, "Project demonstrations", "", "Project (20%) Due: 3-Dec", "CLO 2, 3, 4"),
        W(15, "Course review"),
        W(16, "Final examination", "", "Final (30%) – TBA", "CLO 1, 2, 3, 4"),
    ]],
    programs=[
        dict(name="Computer Engineering", plos=CE_PLOS,
             mapping={1: {1: "H"}, 2: {6: "M", 7: "M"}, 3: {2: "H", 7: "H"}, 4: {2: "M", 4: "M"}},
             addressed=[1, 2, 4, 6, 7]),
        dict(name="Computer Science", plos=CS_PLOS,
             mapping={1: {1: "H"}, 2: {6: "H"}, 3: {2: "H", 6: "M"}, 4: {2: "M", 4: "M"}},
             addressed=[1, 2, 4, 6]),
    ],
)

# --------------------------------------------------------------------------- #
# STAT 100 Intro Probability & Statistics — PDF, Fall 2026
#   V5:  matrix vs schedule disagree on all six assessments (§9 table)
#   V8:  HW2 → CLO 5 (regression) due 2 Nov, regression taught weeks 14–15
#   V9:  Quiz 1 Wed 23 Sep, Midterm Mon 19 Oct, Quiz 2 Mon 9 Nov; class is Tue/Thu
#   V12: prerequisites blank
#   two sections (3:00 and 4:30 Tue/Thu); slightly garbled description
# --------------------------------------------------------------------------- #
STAT100 = dict(
    code="STAT 100", title="Introduction to Probability and Statistics", term="Fall 2026",
    timing="Section 1: Tue/Thu 3:00 - 4:15 PM; Section 2: Tue/Thu 4:30 - 5:45 PM", prereq="",
    description=("This course introduces students to the basic concepts of probability and statistics.Topics "
                 "includedescriptive statistics, probabilityrules, discrete and continuous distributions, "
                 "confidence intervals, hypothesis testing andsimple linear regression and correlation."),
    additional=("Statistical software is used for data analysis throughout the course; examples use real data "
                "on health, business and the environment."),
    textbooks=["Illowsky, B., Dean, S. Introductory Statistics, OpenStax (CC BY 4.0)."],
    clos=[
        "Organize, summarize and display data using descriptive statistics and graphs.",
        "Apply the rules of probability and counting techniques to compute probabilities.",
        "Use discrete and continuous probability distributions, including binomial and normal distributions.",
        "Construct confidence intervals and perform hypothesis tests for a population mean and proportion.",
        "Apply simple linear regression and correlation to analyze bivariate data.",
    ],
    # Matrix CLO sets per §9: Quiz1 {1} Quiz2 {2} Midterm {1,2} HW1 {1} HW2 {5} Final {2,3,4,5}
    assessment_table=matrix(
        ["Quiz 1", "Quiz 2", "Midterm", "HW1", "HW2", "Final"],
        ["5%", "5%", "25%", "10%", "10%", "45%"],
        {1: ["Quiz 1", "Midterm", "HW1"], 2: ["Quiz 2", "Midterm", "Final"], 3: ["Final"], 4: ["Final"],
         5: ["HW2", "Final"]}, 5),
    # Schedule CLO sets per §9: Quiz1 {1,2} Quiz2 {1,4} Midterm {1,2,3} HW1 {2,3} HW2 {1,4} Final {3,4,5}
    weekly_tables=[[
        W(1, "Introduction to statistics; Types of data", "Ch. 1"),
        W(2, "Descriptive statistics: graphs and tables", "Ch. 2.1-2.3"),
        W(3, "Measures of center and spread", "Ch. 2.5-2.8"),
        W(4, "Probability: basic rules", "Ch. 3.1-3.3"),
        W(5, "Counting techniques; Conditional probability", "Ch. 3.4", "Quiz 1 (5%) – 23-09-2026", "CLO 1, 2"),
        W(6, "Discrete random variables; Binomial distribution", "Ch. 4"),
        W(7, "Continuous random variables; Normal distribution", "Ch. 5-6", "HW1 (10%) Due: 12-October", "CLO 2, 3"),
        W(8, "Midterm review", "", "Midterm (25%) – 19-Oct", "CLO 1, 2, 3"),
        W(9, "Sampling distributions; Central limit theorem", "Ch. 7"),
        W(10, "Confidence intervals for a mean", "Ch. 8.1-8.2", "HW2 (10%) Due: 2-Nov", "CLO 1, 4"),
        W(11, "Confidence intervals for a proportion", "Ch. 8.3", "Quiz 2 (5%) – 9 November 2026", "CLO 1, 4"),
        W(12, "Hypothesis testing: one-sample tests", "Ch. 9"),
        W(13, "Hypothesis tests for proportions", "Ch. 9"),
        W(14, "Correlation and simple linear regression", "Ch. 12.1-12.3"),
        W(15, "Regression inference and prediction", "Ch. 12.4-12.6"),
        W(16, "Final examination", "", "Final (45%) – TBA", "CLO 3, 4, 5"),
    ]],
    programs=[dict(name="General Education", plos=GE_PLOS,
                   mapping={1: {2: "H"}, 2: {2: "H"}, 3: {2: "M"}, 4: {2: "H", 3: "M"}, 5: {2: "H", 3: "H"}},
                   addressed=[2, 3])],
)

# file name -> (course dict, format)
COURSES = {
    "CSCI372": (CSCI372, "pdf"),
    "CSAI351": (CSAI351, "docx"),
    "CENG411": (CENG411, "docx"),
    "CENG401": (CENG401, "pdf"),
    "STAT100": (STAT100, "pdf"),
}

# Issues the validator MUST raise, as (rule_id, substring of the flag message).
EXPECTED: dict[str, list[tuple[str, str]]] = {
    "CSCI372": [],
    "CSAI351": [
        ("V4", "quiz 1"),
        ("V7", "outcome 6 is marked 'addressed', but no CLO maps to PLO 6"),
    ],
    "CENG411": [
        ("V2", "'Midterm' 25%"),
        ("V3", "'HW1' (week 3) 5%"),
        ("V3", "'IBM Certification' (10%) is in the weight table but not in the weekly schedule"),
        ("V3", "'Other Activities' (10%) is in the weight table but not in the weekly schedule"),
        ("EX", "fused"),
        ("V7", "CLO 5→PLO 4 is Medium for Computer Engineering but High for Computer Science"),
        ("V7", "CLO 5→PLO 4 is Medium for Computer Engineering but High for AI and Data Science"),
    ],
    "CENG401": [
        ("V11", "Additional Information"),
        ("V6", "'Quiz #2' (week 11) has no CLO"),
        ("V6", "'AWS Lab 2' (week 7) has no CLO"),
        ("V6", "'AWS Lab 4' (week 13) has no CLO"),
        ("V6", "Week 12 maps CLOs {3, 4} but lists no assessment"),
        ("V10", "See Syllabus Guide"),
    ],
    "STAT100": [
        ("V5", "'Quiz 1': the CLO matrix maps CLOs {1}, the weekly schedule maps {1, 2}"),
        ("V5", "'Quiz 2': the CLO matrix maps CLOs {2}, the weekly schedule maps {1, 4}"),
        ("V5", "'Midterm': the CLO matrix maps CLOs {1, 2}, the weekly schedule maps {1, 2, 3}"),
        ("V5", "'HW1': the CLO matrix maps CLOs {1}, the weekly schedule maps {2, 3}"),
        ("V5", "'HW2': the CLO matrix maps CLOs {5}, the weekly schedule maps {1, 4}"),
        ("V5", "'Final': the CLO matrix maps CLOs {2, 3, 4, 5}, the weekly schedule maps {3, 4, 5}"),
        ("V8", "CLO 5's material seems to be taught first in week 14"),
        ("V8", "'HW2' (due 02 Nov)"),
        ("V9", "'Quiz 1' is on Wed 23 Sep 2026"),
        ("V9", "'Midterm' is on Mon 19 Oct 2026"),
        ("V9", "'Quiz 2' is on Mon 09 Nov 2026"),
        ("V12", "Prerequisite course(s) is missing"),
    ],
}

# Rules allowed to fire per course beyond EXPECTED (side effects of the planted issues).
ALLOWED_EXTRA: dict[str, set[str]] = {
    "CSCI372": set(),
    "CSAI351": set(),
    "CENG411": {"V3"},
    "CENG401": set(),
    "STAT100": set(),
}
