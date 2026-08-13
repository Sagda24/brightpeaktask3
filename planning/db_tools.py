import os
import sys
import sqlite3

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from planning.prerequisites import (
    PREREQUISITES,
    PASS_THRESHOLD,
    MAX_CREDITS_PER_SEMESTER,
    prerequisites_for,
)

DB_PATH = os.path.join(PROJECT_ROOT, "DB", "db", "brightpeak.db")

# --------------------------------------------------------------------- #
# Reuse the existing tools instead of re-implementing them.
# The functions in Mcp-Server/server.py stay plain, importable
# callables under @mcp.tool() (FastMCP registers them without hiding
# the underlying function), so we import and call them directly.
# If your fastmcp version wraps them differently, .fn is the fallback.
# --------------------------------------------------------------------- #
def _load_server_tools():
    from Mcp_Server import server as srv  # noqa: N813 (matches repo dir name)
    return srv


def _unwrap(tool):
    return getattr(tool, "fn", tool)


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# --------------------------------------------------------------------- #
# Real handlers registered against Node.tool in registration_agent.py
# --------------------------------------------------------------------- #
def tool_get_profile(student_id: int) -> dict:
    """Reuses the real DB the same way get_student_profile does, keyed
    by id instead of email since the planner already resolved the id."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students WHERE student_id = ?", (student_id,))
    student = cur.fetchone()
    if not student:
        conn.close()
        return {"status": "error", "message": f"Student {student_id} not found."}

    cur.execute(
        """SELECT c.course_id, c.title, e.grade, e.status
           FROM enrollments e JOIN courses c ON e.course_id = c.course_id
           WHERE e.student_id = ?""",
        (student_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"status": "success", "student": dict(student), "history": rows}


def tool_check_prerequisites(student_id: int, course_id: int) -> dict:
    """GROUNDED check (real DB query + PRE-001/GRD-001/RET-001 policy),
    not an LLM opinion. This is the environment feedback source that
    later replaces the toolkit's randomized environment.py default."""
    profile = tool_get_profile(student_id)
    if profile["status"] != "success":
        return profile

    completed_passed = {
        row["course_id"]
        for row in profile["history"]
        if row["status"] == "COMPLETED" and (row["grade"] or 0) >= PASS_THRESHOLD
    }
    attempted_failed = {
        row["course_id"]: row["grade"]
        for row in profile["history"]
        if row["status"] in ("COMPLETED", "DROPPED")
        and (row["grade"] or 0) < PASS_THRESHOLD
    }

    required = prerequisites_for(course_id)
    missing = [c for c in required if c not in completed_passed]

    if not missing:
        return {"status": "success", "eligible": True, "missing_prereqs": []}

    needs_retake = [c for c in missing if c in attempted_failed]
    return {
        "status": "success",
        "eligible": False,
        "missing_prereqs": missing,
        "needs_retake": needs_retake,  # attempted but failed -> RET-001 applies
        "reason": (
            f"course {course_id} requires passing course(s) {required}; "
            f"student is missing {missing} "
            f"(policy PRE-001 / GRD-001 / RET-001)"
        ),
    }


def tool_enroll(student_id: int, course_id: int) -> dict:
    """Calls the REAL enroll_student tool from the MCP server. Note this
    tool does not itself enforce prerequisites (see server.py) — that
    is exactly why check_prerequisites must run before it in the DAG,
    and why a plan that skips straight to enroll is a genuine bug, not
    a stylistic nitpick."""
    try:
        srv = _load_server_tools()
        enroll_fn = _unwrap(srv.enroll_student)
        return enroll_fn(student_id=student_id, course_id=course_id)
    except Exception as e:
        # Fallback: same logic as server.py, direct DB, for environments
        # where fastmcp/Mcp-Server isn't importable (e.g. this sandbox).
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT student_id FROM students WHERE student_id=?", (student_id,))
            if not cur.fetchone():
                return {"status": "error", "message": f"Student ID {student_id} does not exist."}
            cur.execute("SELECT course_id FROM courses WHERE course_id=?", (course_id,))
            if not cur.fetchone():
                return {"status": "error", "message": f"Course ID {course_id} does not exist."}
            cur.execute(
                "SELECT enrollment_id FROM enrollments WHERE student_id=? AND course_id=?",
                (student_id, course_id),
            )
            if cur.fetchone():
                return {"status": "error", "message": "Student is already enrolled in this course."}
            cur.execute(
                "INSERT INTO enrollments (student_id, course_id, status) VALUES (?, ?, 'ENROLLED')",
                (student_id, course_id),
            )
            conn.commit()
            return {
                "status": "success",
                "message": f"Successfully enrolled student {student_id} in course {course_id}.",
                "note": f"(direct-DB fallback path, import error: {e})",
            }
        finally:
            conn.close()


def tool_search_policy(query: str, top_k: int = 3) -> dict:
    """Calls the real search_knowledge_base tool for grounding a
    student-facing explanation in the actual policy text."""
    try:
        srv = _load_server_tools()
        search_fn = _unwrap(srv.search_knowledge_base)
        return search_fn(query=query, top_k=top_k)
    except Exception:
        # Minimal local fallback using the same knowledge base file,
        # for environments without fastmcp installed.
        import json
        kb_path = os.path.join(PROJECT_ROOT, "rag", "knowledge_base", "knowledge_base.json")
        with open(kb_path) as f:
            docs = json.load(f)
        terms = query.lower().split()
        scored = sorted(
            docs,
            key=lambda d: sum(t in d["text"].lower() for t in terms),
            reverse=True,
        )
        return {
            "status": "success",
            "results": [
                {"title": d["title"], "content": d["text"]} for d in scored[:top_k]
            ],
        }


def tool_credit_load(student_id: int, additional_course_ids: list) -> dict:
    """GROUNDED semester overload check against MAX_CREDITS_PER_SEMESTER."""
    conn = get_db_connection()
    cur = conn.cursor()
    placeholders = ",".join("?" * len(additional_course_ids)) or "NULL"
    cur.execute(
        f"SELECT course_id, credits FROM courses WHERE course_id IN ({placeholders})",
        additional_course_ids,
    )
    credits = sum(r["credits"] for r in cur.fetchall())
    conn.close()
    return {
        "status": "success",
        "requested_credits": credits,
        "limit": MAX_CREDITS_PER_SEMESTER,
        "within_limit": credits <= MAX_CREDITS_PER_SEMESTER,
    }


# registry used by both decomposition.py and dynamic_decomposition.py
TOOL_REGISTRY = {
    "get_profile": tool_get_profile,
    "check_prerequisites": tool_check_prerequisites,
    "enroll": tool_enroll,
    "search_policy": tool_search_policy,
    "credit_load": tool_credit_load,
}
