import random

FACT_TEMPLATES = [
    {
        "type": "prerequisite_waiver",
        "student_line": (
            "Before we go further -- I already have an approved prerequisite "
            "waiver for {course}, signed off by Dr. Mahmoud Abdelrahman last month."
        ),
        "marker": "approved prerequisite waiver for {course}",
        "final_question": (
            "Great, let's finalize your enrollment in {course}. Before I submit it, "
            "are there any prerequisite waivers or holds on file I should account for?"
        ),
    },
    {
        "type": "registration_hold_cleared",
        "student_line": (
            "One thing you should know: I had a registration hold on my account for "
            "unpaid tuition, but the bursar's office cleared it on {date}."
        ),
        "marker": "registration hold on my account for unpaid tuition, but the bursar's office cleared it",
        "final_question": (
            "Okay, I'm about to process your enrollment. Is there anything about "
            "holds on your account I should double check first?"
        ),
    },
    {
        "type": "credit_overload_exception",
        "student_line": (
            "Also, my academic advisor approved a credit overload exception so I "
            "can take up to 21 credits this semester instead of the usual 18."
        ),
        "marker": "credit overload exception so I can take up to 21 credits",
        "final_question": (
            "This would bring you to 20 credits this semester, which is above the "
            "normal 18-credit cap. Is there an exception on file for that?"
        ),
    },
    {
        "type": "transfer_credit",
        "student_line": (
            "I should mention I already completed the equivalent of {course} at my "
            "previous university, and BrightPeak's registrar approved it as transfer credit."
        ),
        "marker": "approved it as transfer credit",
        "final_question": (
            "Before I enroll you in {course}, do you have any transfer credit or "
            "prior equivalent coursework on file for it?"
        ),
    },
]

COURSES = [
    "Advanced Machine Learning",
    "Database Management Systems",
    "Software Engineering Principles",
    "Artificial Intelligence Ethics",
]

STUDENT_NAMES = [
    ("Omar Khaled", "omar.k@brightpeak.edu"),
    ("Youssef Ibrahim", "youssef.i@brightpeak.edu"),
    ("Hoda Mansour", "hoda.m@brightpeak.edu"),
    ("Kareem Reda", "kareem.r@brightpeak.edu"),
    ("Salma Farouk", "salma.f@brightpeak.edu"),
]

KB_DOCS = [
    ("Attendance Policy", "Students must maintain at least 75% attendance in every course. "
                           "Students below this limit may be prevented from taking the final exam."),
    ("Grading Policy", "Grades are assigned on a scale from 0 to 100. A grade of 60 or above "
                        "is considered a passing grade."),
    ("Course Registration", "Students may enroll only in courses for which all prerequisites "
                             "have been completed successfully."),
    ("Academic Warning", "Students with poor academic performance may receive an academic "
                          "warning and should meet their academic advisor."),
    ("Graduation Requirements", "Students must complete all required courses and earn the "
                                 "required credit hours before graduation."),
]


def _tool_result_student_profile(name, email, rng):
    courses = rng.sample(range(1, 9), k=min(6, 8))
    lines = [f'{{"student_id": {rng.randint(1,50)}, "name": "{name}", "email": "{email}", "role": "STUDENT",']
    lines.append('"enrolled_courses": [')
    titles = COURSES + ["Introduction to Computer Science", "Data Structures", "Operating Systems",
                         "Linear Algebra for CS", "Technical Writing", "Discrete Mathematics"]
    for i, cid in enumerate(courses):
        title = titles[cid % len(titles)]
        grade = round(rng.uniform(55, 99), 1)
        status = rng.choice(["COMPLETED", "ENROLLED", "COMPLETED", "DROPPED"])
        lines.append(f'  {{"title": "{title}", "grade": {grade}, "status": "{status}"}},')
    lines.append("]}")
    return "\n".join(lines)


def _tool_result_course_list(rng):
    titles = COURSES + ["Introduction to Computer Science", "Data Structures", "Operating Systems",
                         "Linear Algebra for CS", "Technical Writing", "Discrete Mathematics",
                         "Compilers", "Computer Networks", "Human-Computer Interaction"]
    lines = ["["]
    for i, t in enumerate(titles):
        lines.append(
            f'  {{"course_id": {i+1}, "title": "{t}", "credits": {rng.choice([2,3,4])}, '
            f'"instructor_name": "Dr. {rng.choice(["Hassan","Jenkins","Abdelrahman","Zaki","Farid","Nabil"])}"}},'
        )
    lines.append("]")
    return "\n".join(lines)


def _tool_result_kb_search(rng):
    doc = rng.choice(KB_DOCS)
    return f'{{"title": "{doc[0]}", "content": "{doc[1]}", "score": {round(rng.uniform(0.4, 0.9), 2)}}}'


def _tool_result_academic_report(rng):
    return (
        f'{{"status": "success", "report_summary": {{"total_students": {rng.randint(80,200)}, '
        f'"total_courses": {rng.randint(10,20)}, "status": "Completed all evaluation steps"}}}}'
    )


NOISE_TOOL_CALLS = [
    ("get_student_profile", _tool_result_student_profile),
    ("list_all_courses", _tool_result_course_list),
    ("search_knowledge_base", _tool_result_kb_search),
    ("generate_academic_report", _tool_result_academic_report),
]

FILLER_DIALOGUE = [
    ("student", "Okay, can you also check what electives are open this term?"),
    ("agent", "Sure, let me pull that up for you."),
    ("student", "And what's the deadline to add or drop a course?"),
    ("agent", "One moment, checking the registrar's calendar."),
    ("student", "Also, is Dr. Hassan still teaching the intro course?"),
    ("agent", "Let me confirm that against the current course list."),
    ("student", "Can you check if I have any outstanding academic warnings?"),
    ("agent", "Pulling your academic report now."),
    ("student", "Sorry, one more -- what's the passing grade threshold again?"),
    ("agent", "Let me check the grading policy for you."),
]


def _build_transcript(idx, fact_template, name_pair, noise_turns, critical_turn_pos, seed):
    rng = random.Random(seed)
    name, email = name_pair
    course = rng.choice(COURSES)
    date = rng.choice(["March 3rd", "last Tuesday", "the 12th of this month", "two weeks ago"])

    turns = []
    t = 0

    def add(speaker, ttype, content, tool_name=None, is_critical=False):
        nonlocal t
        t += 1
        turns.append({
            "turn": t, "speaker": speaker, "type": ttype, "tool_name": tool_name,
            "content": content, "is_critical": is_critical,
        })

    add("student", "dialogue", f"Hi, this is {name}. I'd like to talk through my schedule for next semester.")
    add("agent", "dialogue", "Sure, let me pull up your profile first.")
    add("tool", "tool_call", f"get_student_profile(email='{email}')", tool_name="get_student_profile")
    add("tool", "tool_result", _tool_result_student_profile(name, email, rng), tool_name="get_student_profile")

    marker = fact_template["marker"].format(course=course)
    student_line = fact_template["student_line"].format(course=course, date=date)
    final_question = fact_template["final_question"].format(course=course)

    # Place the critical fact near the start (position varies per transcript,
    # matching the lab's "buried under later tool noise" shape).
    inserted_critical = False

    for i in range(noise_turns):
        if not inserted_critical and i == critical_turn_pos:
            add("student", "dialogue", student_line, is_critical=True)
            add("agent", "dialogue", "Got it, thanks for letting me know -- I'll keep that in mind.")
            inserted_critical = True
            continue

        tool_name, gen = rng.choice(NOISE_TOOL_CALLS)
        if tool_name == "get_student_profile":
            call = f"get_student_profile(email='{email}')"
        elif tool_name == "list_all_courses":
            call = "list_all_courses()"
        elif tool_name == "search_knowledge_base":
            call = f"search_knowledge_base(query='{rng.choice(['attendance','grading','graduation','registration'])}')"
        else:
            call = "generate_academic_report()"

        add("tool", "tool_call", call, tool_name=tool_name)
        add("tool", "tool_result", gen(rng) if tool_name != "get_student_profile" else gen(name, email, rng),
            tool_name=tool_name)

        if rng.random() < 0.35:
            spk, line = rng.choice(FILLER_DIALOGUE)
            add(spk, "dialogue", line)

    if not inserted_critical:
        add("student", "dialogue", student_line, is_critical=True)
        add("agent", "dialogue", "Got it, thanks for letting me know -- I'll keep that in mind.")

    add("agent", "dialogue", final_question, is_critical=True)

    return {
        "id": f"transcript_{idx:02d}_{fact_template['type']}",
        "fact_type": fact_template["type"],
        "critical_marker": marker,
        "final_question": final_question,
        "turns": turns,
    }


def build_test_suite():
    """Ten fixed transcript variations across all four fact types, at
    different critical-turn positions and noise volumes, exactly as required:
    'a real long-context test suite ... kept fixed once you start evaluating.'
    DO NOT regenerate with a new seed after evaluation has started -- the
    seeds below are fixed for reproducibility."""
    configs = [
        (0, FACT_TEMPLATES[0], STUDENT_NAMES[0], 32, 2, 101),
        (1, FACT_TEMPLATES[1], STUDENT_NAMES[1], 36, 3, 102),
        (2, FACT_TEMPLATES[2], STUDENT_NAMES[2], 30, 1, 103),
        (3, FACT_TEMPLATES[3], STUDENT_NAMES[3], 34, 4, 104),
        (4, FACT_TEMPLATES[0], STUDENT_NAMES[4], 38, 2, 105),
        (5, FACT_TEMPLATES[1], STUDENT_NAMES[0], 28, 1, 106),
        (6, FACT_TEMPLATES[2], STUDENT_NAMES[1], 40, 3, 107),
        (7, FACT_TEMPLATES[3], STUDENT_NAMES[2], 33, 2, 108),
        (8, FACT_TEMPLATES[0], STUDENT_NAMES[3], 35, 5, 109),
        (9, FACT_TEMPLATES[1], STUDENT_NAMES[4], 31, 2, 110),
    ]
    return [_build_transcript(*cfg) for cfg in configs]


if __name__ == "__main__":
    suite = build_test_suite()
    for tr in suite:
        total_chars = sum(len(t["content"]) for t in tr["turns"])
        print(f"{tr['id']}: {len(tr['turns'])} turns, ~{total_chars//4} tokens, "
              f"marker={tr['critical_marker'][:50]!r}")
