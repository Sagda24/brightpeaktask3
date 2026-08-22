import os
import sys

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import sqlite3
import os
import re
from fastmcp import FastMCP, Context
from rag.decompose_search import combine_search
from rank_bm25 import BM25Okapi
from rag.hybrid_rag import hybrid_search
import rag.hybrid_rag as hybrid_rag_module
from rag.agentic_rag import agentic_retrieve
from rag.naive_rag import naive_rag_answer
import rag.naive_rag as naive_rag_module
from rag.knowledge_base.loader import (
    load_knowledge_base,
    add_document as kb_add_document,
    remove_document as kb_remove_document,
    list_documents as kb_list_documents,
)


class _KeywordIndex:
    """Holds the BM25 index used by search_knowledge_base.

    This used to be three bare module-level globals (knowledge_documents,
    tokenized_docs, bm25) built once at import time, which meant the
    knowledge base could never change without restarting the process.
    Wrapping them in one object with a rebuild() method is what lets
    add_knowledge_document / remove_knowledge_document (below) refresh
    keyword search without a restart.
    """

    def __init__(self):
        self.rebuild()

    def rebuild(self):
        self.documents = load_knowledge_base()
        tokenized = [doc["text"].lower().split() for doc in self.documents]
        self.bm25 = BM25Okapi(tokenized)
        return len(self.documents)


keyword_index = _KeywordIndex()

mcp = FastMCP("Brightpeak Academy Server")

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "DB", "db", "brightpeak.db")


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@mcp.tool()
def get_student_profile(email: str) -> dict:
    # 1. Input Validation:
    email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    if not re.match(email_regex, email):
        return {"status": "error", "message": "Invalid email format."}

    conn = get_db_connection()
    cursor = conn.cursor()

    # 2. Logic Validation:
    cursor.execute("SELECT * FROM students WHERE email = ?", (email,))
    student = cursor.fetchone()

    if not student:
        conn.close()
        return {"status": "error", "message": f"Student with email '{email}' not found."}

    # 3. Fetching Enrolled Courses and Grades
    query = """
        SELECT c.title, e.grade, e.status 
        FROM enrollments e
        JOIN courses c ON e.course_id = c.course_id
        WHERE e.student_id = ?
    """
    cursor.execute(query, (student["student_id"],))
    courses = cursor.fetchall()
    conn.close()

    return {
        "status": "success",
        "data": {
            "student_id": student["student_id"],
            "name": student["name"],
            "email": student["email"],
            "role": student["role"],
            "enrolled_courses": [dict(row) for row in courses]
        }
    }


@mcp.tool(
    name="get_student_profile_by_id",
    description="Fetches a student's profile and enrolled courses by numeric student_id. Same data as get_student_profile, keyed by id instead of email."
)
def get_student_profile_by_id(student_id: int) -> dict:
    # 1. Input Validation:
    if student_id <= 0:
        return {"status": "error", "message": "student_id must be a positive integer."}

    conn = get_db_connection()
    cursor = conn.cursor()

    # 2. Logic Validation:
    cursor.execute("SELECT * FROM students WHERE student_id = ?", (student_id,))
    student = cursor.fetchone()

    if not student:
        conn.close()
        return {"status": "error", "message": f"Student ID {student_id} not found."}

    # 3. Fetching Enrolled Courses and Grades
    query = """
        SELECT c.title, e.grade, e.status 
        FROM enrollments e
        JOIN courses c ON e.course_id = c.course_id
        WHERE e.student_id = ?
    """
    cursor.execute(query, (student["student_id"],))
    courses = cursor.fetchall()
    conn.close()

    return {
        "status": "success",
        "data": {
            "student_id": student["student_id"],
            "name": student["name"],
            "email": student["email"],
            "role": student["role"],
            "enrolled_courses": [dict(row) for row in courses]
        }
    }


@mcp.tool()
def list_all_courses() -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT c.course_id, c.title, c.credits, i.name as instructor_name
        FROM courses c
        LEFT JOIN instructors i ON c.instructor_id = i.instructor_id
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()

    return {
        "status": "success",
        "courses": [dict(row) for row in rows]
    }


@mcp.tool()
def enroll_student(student_id: int, course_id: int) -> dict:
    # 1. Input Validation:
    if student_id <= 0 or course_id <= 0:
        return {"status": "error", "message": "Student ID and Course ID must be positive integers."}

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 2. Logic Validation
        cursor.execute("SELECT student_id FROM students WHERE student_id = ?", (student_id,))
        if not cursor.fetchone():
            return {"status": "error", "message": f"Student ID {student_id} does not exist."}

        # 3. Logic Validation:
        cursor.execute("SELECT course_id FROM courses WHERE course_id = ?", (course_id,))
        if not cursor.fetchone():
            return {"status": "error", "message": f"Course ID {course_id} does not exist."}

        # 4. Duplicate Check:
        cursor.execute(
            "SELECT enrollment_id FROM enrollments WHERE student_id = ? AND course_id = ?",
            (student_id, course_id)
        )
        if cursor.fetchone():
            return {"status": "error", "message": "Student is already enrolled in this course."}

        # 5. Insert Enrollment Record
        cursor.execute(
            "INSERT INTO enrollments (student_id, course_id, status) VALUES (?, ?, 'ENROLLED')",
            (student_id, course_id)
        )
        conn.commit()
        return {"status": "success", "message": f"Successfully enrolled student {student_id} in course {course_id}."}

    except Exception as e:
        return {"status": "error", "message": f"Database exception: {str(e)}"}
    finally:
        conn.close()


@mcp.tool(
    name="update_student_grade",
    description="Updates a student's grade for a specific course. Requires INSTRUCTOR or ADMIN role and strict input validation."
)
def update_student_grade(student_id: int, course_id: int, new_grade: float, requester_role: str) -> dict:
    # 1. Authorization Check
    allowed_roles = ["INSTRUCTOR", "ADMIN"]
    if requester_role not in allowed_roles:
        return {
            "status": "error",
            "message": f"Authorization denied. Role '{requester_role}' is not permitted to modify grades."
        }

    # 2. Server-side Validation
    if not (0.0 <= new_grade <= 100.0):
        return {
            "status": "error",
            "message": "Invalid grade. Grade must be between 0.0 and 100.0."
        }

    if student_id <= 0 or course_id <= 0:
        return {
            "status": "error",
            "message": "Student ID and Course ID must be positive integers."
        }

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 3. Check if enrollment exists
        cursor.execute(
            "SELECT enrollment_id FROM enrollments WHERE student_id = ? AND course_id = ?",
            (student_id, course_id)
        )
        enrollment = cursor.fetchone()

        if not enrollment:
            return {
                "status": "error",
                "message": f"No active enrollment found for Student ID {student_id} in Course ID {course_id}."
            }

        # 4. Perform Update
        cursor.execute(
            "UPDATE enrollments SET grade = ?, status = 'COMPLETED' WHERE student_id = ? AND course_id = ?",
            (new_grade, student_id, course_id)
        )
        conn.commit()

        return {
            "status": "success",
            "message": f"Successfully updated grade for student {student_id} in course {course_id} to {new_grade}."
        }

    except Exception as e:
        return {"status": "error", "message": f"Database exception: {str(e)}"}
    finally:
        conn.close()


import time


@mcp.tool(
    name="generate_academic_report",
    description="Generates a comprehensive academic report for all courses and students."
)
async def generate_academic_report(ctx: Context) -> dict:
    import asyncio

    await ctx.report_progress(progress=0, total=100)

    await asyncio.sleep(1)
    await ctx.report_progress(30, 100, "Collecting student records...")

    await asyncio.sleep(1)
    await ctx.report_progress(70, 100, "Analyzing grades...")

    await asyncio.sleep(1)
    await ctx.report_progress(100, 100, "Generating final report...")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as student_count FROM students")
    student_count = cursor.fetchone()["student_count"]

    cursor.execute("SELECT COUNT(*) as course_count FROM courses")
    course_count = cursor.fetchone()["course_count"]

    conn.close()

    return {
        "status": "success",
        "message": "Academic report generated successfully with progress tracking.",
        "report_summary": {
            "total_students": student_count,
            "total_courses": course_count,
            "status": "Completed all evaluation steps"
        }
    }


@mcp.tool(
    name="request_student_evaluation",
    description="Requests the client model to evaluate a student's academic standing based on their grades using sampling."
)
async def request_student_evaluation(student_id: int, ctx: Context) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get student information
    cursor.execute(
        "SELECT name, email FROM students WHERE student_id = ?",
        (student_id,)
    )
    student = cursor.fetchone()

    if not student:
        conn.close()
        return {
            "status": "error",
            "message": f"Student ID {student_id} not found."
        }

    # Get enrolled courses
    query = """
         SELECT c.title, e.grade, e.status
         FROM enrollments e
         JOIN courses c ON e.course_id = c.course_id
         WHERE e.student_id = ?
     """

    cursor.execute(query, (student_id,))
    courses = cursor.fetchall()
    conn.close()

    # Build prompt
    course_details = ""

    for course in courses:
        course_details += (
            f"- {course['title']}\n"
            f"  Grade : {course['grade']}\n"
            f"  Status: {course['status']}\n\n"
        )

    prompt = f"""
    You are an academic advisor.

    Evaluate the academic performance of the following student.

    Student Name:
    {student['name']}

    Courses:
    {course_details}

    Please provide:

    1. Overall Performance
    2. Strengths
    3. Weaknesses
    4. Recommendation

    Keep the response concise and professional.
    """

    # Ask the client model
    response = await ctx.sample(
        messages=prompt,
        max_tokens=150
    )

    return {
        "status": "success",
        "evaluation": response.text
    }


@mcp.tool(
    name="search_knowledge_base",
    description="Searches the academy knowledge base using keyword retrieval."
)
def search_knowledge_base(query: str, top_k: int = 3) -> dict:
    if top_k < 1:
        top_k = 1

    if top_k > 5:
        top_k = 5

    query_tokens = query.lower().split()

    scores = keyword_index.bm25.get_scores(query_tokens)

    ranked = sorted(
        zip(scores, keyword_index.documents),
        key=lambda x: x[0],
        reverse=True
    )

    results = []

    for score, doc in ranked[:top_k]:
        if score > 0:
            results.append({
                "title": doc["title"],
                "content": doc["text"],
                "score": round(float(score), 2)
            })

    if not results:
        return {
            "status": "success",
            "message": "No relevant documents found.",
            "results": []
        }

    return {
        "status": "success",
        "results": results
    }


@mcp.tool(
    name="naive_rag",
    description=(
            "Answers academic knowledge questions "
            "using Naive RAG with vector retrieval "
            "and Self-RAG verification."
    )
)
async def naive_rag(
        query: str,
        ctx: Context
) -> dict:
    return await naive_rag_answer(
        query,
        ctx
    )


@mcp.tool(
    name="hybrid_rag",
    description=(
            "Retrieves academy knowledge using "
            "vector similarity and BM25 keyword search."
    )
)
def hybrid_rag(
        query: str,
        top_k: int = 3
) -> dict:
    results = hybrid_search(
        query,
        top_k=top_k
    )

    return {
        "status": "success",
        "results": results
    }


@mcp.tool(
    name="decompose_and_search",
    description=(
            "Decomposes a compound question into smaller sub-questions "
            "and searches the knowledge base for each one."
    )
)
async def decompose_and_search(
        query: str,
        top_k: int = 3,
        ctx: Context = None
) -> dict:
    if top_k < 1:
        top_k = 1

    if top_k > 5:
        top_k = 5

    results = await combine_search(
        query=query,
        search_tool=search_knowledge_base,
        ctx=ctx,
        top_k=top_k
    )

    return {
        "status": "success",
        "original_query": query,
        "results": [
            {
                "sub_question": result.sub_question,
                "content": result.chunk,
                "score": result.score
            }
            for result in results
        ]
    }


# ============================================================
# RAG document add/remove backend
#
# knowledge_base.json is the source of truth (rag/knowledge_base/loader.py
# owns the actual read-modify-write). These three tools are the MCP-facing
# surface over it, and are the ONLY way a document should be added or
# removed at runtime: each write is followed by rebuilding every retrieval
# index that was previously frozen at process start (this server's BM25
# keyword index, naive_rag's embeddings/FAISS index, hybrid_rag's BM25
# index) so search_knowledge_base / naive_rag / hybrid_rag / agentic
# retrieval (which is built on top of naive_rag + hybrid_rag) all see the
# change immediately, without a server restart.
# ============================================================

@mcp.tool(
    name="list_knowledge_documents",
    description="Lists the id, title and category of every document currently in the academic policy knowledge base."
)
def list_knowledge_documents() -> dict:
    return {"status": "success", "documents": kb_list_documents()}


@mcp.tool(
    name="add_knowledge_document",
    description=(
        "Adds a new academic policy document to the knowledge base and "
        "rebuilds keyword and vector retrieval so it is searchable "
        "immediately. Requires ADMIN role."
    )
)
def add_knowledge_document(
    document_id: str,
    title: str,
    text: str,
    requester_role: str,
    category: str = "general",
    department: str = "Academic Affairs",
) -> dict:
    if requester_role not in ("ADMIN",):
        return {
            "status": "error",
            "message": f"Role '{requester_role}' is not permitted to modify the knowledge base."
        }

    try:
        document = kb_add_document({
            "id": document_id,
            "title": title,
            "text": text,
            "category": category,
            "department": department,
        })
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    keyword_index.rebuild()
    naive_rag_module.rebuild_vector_store()
    hybrid_rag_module.rebuild_bm25()

    return {
        "status": "success",
        "message": f"Document '{document_id}' added and retrieval indexes rebuilt.",
        "document": document,
    }


@mcp.tool(
    name="remove_knowledge_document",
    description=(
        "Removes an academic policy document from the knowledge base by id "
        "and rebuilds keyword and vector retrieval. Requires ADMIN role."
    )
)
def remove_knowledge_document(document_id: str, requester_role: str) -> dict:
    if requester_role not in ("ADMIN",):
        return {
            "status": "error",
            "message": f"Role '{requester_role}' is not permitted to modify the knowledge base."
        }

    removed = kb_remove_document(document_id)

    if not removed:
        return {
            "status": "error",
            "message": f"Document '{document_id}' not found."
        }

    keyword_index.rebuild()
    naive_rag_module.rebuild_vector_store()
    hybrid_rag_module.rebuild_bm25()

    return {
        "status": "success",
        "message": f"Document '{document_id}' removed and retrieval indexes rebuilt.",
    }


# ============================================================
# Runtime tool registration / removal
#
# FastMCP already supports adding/removing tools on a live server via
# mcp.add_tool() / mcp.remove_tool() — see:
# https://gofastmcp.com/servers/tools (Runtime Tool Management).
# These two admin tools expose that safely: rather than registering
# arbitrary code sent over the wire (an obvious injection risk), an admin
# can only turn tools on/off from a fixed, reviewed catalog defined in
# this file (_OPTIONAL_TOOLS), plus remove any currently active tool
# (including core ones, if an admin needs to take one out of service).
# list_registered_tools() lets the client discover what's active vs.
# available before calling either one.
# ============================================================

def _tool_list_all_instructors() -> dict:
    """Optional tool: not registered by default. Demonstrates a tool
    being added to a running server without a restart."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT instructor_id, name FROM instructors")

    rows = cursor.fetchall()
    conn.close()

    return {
        "status": "success",
        "instructors": [dict(row) for row in rows]
    }


def _tool_course_enrollment_counts() -> dict:
    """Optional tool: not registered by default."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT c.course_id, c.title, COUNT(e.enrollment_id) as enrolled_count
        FROM courses c
        LEFT JOIN enrollments e ON c.course_id = e.course_id
        GROUP BY c.course_id
        """
    )

    rows = cursor.fetchall()
    conn.close()

    return {
        "status": "success",
        "courses": [dict(row) for row in rows]
    }


_OPTIONAL_TOOLS = {
    "list_all_instructors": {
        "fn": _tool_list_all_instructors,
        "description": "Lists every instructor's id and name.",
    },

    "course_enrollment_counts": {
        "fn": _tool_course_enrollment_counts,
        "description": "Lists every course with how many students are currently enrolled in it.",
    },
}


@mcp.tool(
    name="list_registered_tools",
    description="Lists every tool currently active on this server, plus which optional tools from the catalog are available to register."
)
async def list_registered_tools() -> dict:

    active = sorted((await mcp.get_tools()).keys())

    return {
        "status": "success",
        "active_tools": active,
        "registerable": [
            name
            for name in _OPTIONAL_TOOLS
            if name not in active
        ],
    }


@mcp.tool(
    name="register_tool",
    description=(
        "Registers one of the optional catalog tools on this running server "
        "at runtime, without a restart. Requires ADMIN role."
    )
)
async def register_tool(tool_name: str, requester_role: str) -> dict:

    if requester_role != "ADMIN":
        return {
            "status": "error",
            "message": f"Role '{requester_role}' is not permitted to register tools."
        }

    if tool_name not in _OPTIONAL_TOOLS:
        return {
            "status": "error",
            "message": (
                f"'{tool_name}' is not in the optional tool catalog: "
                f"{list(_OPTIONAL_TOOLS)}"
            ),
        }

    active = await mcp.get_tools()

    if tool_name in active:
        return {
            "status": "error",
            "message": f"Tool '{tool_name}' is already registered."
        }

    entry = _OPTIONAL_TOOLS[tool_name]

    mcp.add_tool(
        entry["fn"],
        name=tool_name,
        description=entry["description"]
    )

    return {
        "status": "success",
        "message": f"Tool '{tool_name}' registered."
    }


@mcp.tool(
    name="remove_tool",
    description=(
        "Removes a tool from this running server at runtime, without a "
        "restart. Requires ADMIN role. Cannot remove register_tool, "
        "remove_tool or list_registered_tools themselves."
    )
)
async def remove_tool(tool_name: str, requester_role: str) -> dict:

    if requester_role != "ADMIN":
        return {
            "status": "error",
            "message": f"Role '{requester_role}' is not permitted to remove tools."
        }

    if tool_name in (
        "register_tool",
        "remove_tool",
        "list_registered_tools"
    ):
        return {
            "status": "error",
            "message": f"Refusing to remove admin tool '{tool_name}'."
        }

    active = await mcp.get_tools()

    if tool_name not in active:
        return {
            "status": "error",
            "message": f"Tool '{tool_name}' is not currently registered."
        }

    mcp.remove_tool(tool_name)

    return {
        "status": "success",
        "message": f"Tool '{tool_name}' removed."
    }


import sys

if __name__ == "__main__":

    if len(sys.argv) > 1 and sys.argv[1] == "http":

        mcp.run(
            transport="streamable-http",
            host="127.0.0.1",
            port=8000
        )

    else:

        mcp.run(
            transport="stdio"
        )
