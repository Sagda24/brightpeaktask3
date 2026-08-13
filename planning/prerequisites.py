PASS_THRESHOLD = 60.0          # GRD-001
MAX_CREDITS_PER_SEMESTER = 7   # academy norm used for overload checks

# course_id -> list of course_ids that must be *passed* first
PREREQUISITES = {
    1: [],      # Introduction to Computer Science — no prerequisite
    3: [1],     # Database Management Systems needs Intro to CS
    4: [1],     # Software Engineering Principles needs Intro to CS
    2: [1, 3],  # Advanced Machine Learning needs Intro to CS + DBMS
    5: [],      # Artificial Intelligence Ethics — open elective
}


def prerequisites_for(course_id: int) -> list:
    return PREREQUISITES.get(course_id, [])
