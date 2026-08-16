"""
routes/quiz.py
---------------
Handles question generation and answer submission for ALL three test types:

    POST /api/quiz/start   - generate questions for placement / level_up / skill_test
    POST /api/quiz/submit  - save student answers for a session

Design notes:
  - A quiz_session row is created first, then questions are inserted.
  - The session id is returned to the frontend so it can submit answers
    against that exact session later.
  - FIFO cleanup is triggered here before generating level_up questions
    (keeps only last 2 sessions per the design doc, Section 10).
  - For skill_test: the previous session's questions/answers for that
    skill are deleted before new ones are inserted (latest-attempt-only).
"""

from flask import Blueprint, request, jsonify, g
from datetime import datetime, timezone

from config.db import get_db_connection
from utils.auth import token_required
from services.groq_service import generate_placement_questions, generate_test_questions
from services.fifo_service import cleanup_level_up_sessions, cleanup_skill_test_session

quiz_bp = Blueprint("quiz", __name__)


# ============================================================
# POST /api/quiz/start
# ============================================================
@quiz_bp.route("/quiz/start", methods=["POST"])
@token_required
def start_quiz():
    """
    Generate questions for a quiz session and persist them to the DB.

    Expected JSON body:
        {
          "test_type": "placement" | "level_up" | "skill_test",
          "skill_id": 12          # required only for skill_test
        }

    The route fetches the student's dream career, academics, and current
    level from the DB so callers do not need to send that context.

    On success (201):
        {
          "session_id": 7,
          "test_type": "placement",
          "level": 1,
          "questions": [
            {
              "id": 101,
              "question_number": 1,
              "question_text": "...",
              "question_type": "mcq",
              "options": ["A","B","C","D"]
              // correct_answer is NEVER sent to the frontend
            },
            ...
          ]
        }
    """
    data = request.get_json(silent=True) or {}
    test_type = (data.get("test_type") or "").strip()
    skill_id  = data.get("skill_id")

    if test_type not in ("placement", "level_up", "skill_test"):
        return jsonify({"error": "test_type must be placement, level_up, or skill_test"}), 400

    if test_type == "skill_test" and not skill_id:
        return jsonify({"error": "skill_id is required for skill_test"}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

            # --- Fetch student context needed by the AI ---
            cursor.execute(
                "SELECT dream_career FROM student_profiles WHERE user_id = %s",
                (g.user_id,)
            )
            profile = cursor.fetchone()
            if not profile:
                return jsonify({"error": "Please set your dream career first"}), 422

            dream = profile["dream_career"]

            cursor.execute(
                "SELECT subject, grade, gpa FROM academic_results WHERE user_id = %s",
                (g.user_id,)
            )
            academics = cursor.fetchall()

            # Current level (defaults to 1 if no row yet - placement test
            # case where skill_levels hasn't been written yet)
            cursor.execute(
                "SELECT current_level FROM skill_levels WHERE user_id = %s AND career = %s",
                (g.user_id, dream)
            )
            level_row = cursor.fetchone()
            current_level = level_row["current_level"] if level_row else 1

            # --- Extra context for skill_test ---
            skill_name = None
            if test_type == "skill_test":
                cursor.execute(
                    "SELECT skill_name, level FROM skill_tree WHERE id = %s AND user_id = %s",
                    (skill_id, g.user_id)
                )
                skill_row = cursor.fetchone()
                if not skill_row:
                    return jsonify({"error": "Skill not found"}), 404
                skill_name    = skill_row["skill_name"]
                current_level = skill_row["level"]

            # --- Determine attempt_number for level_up ---
            attempt_number = 1
            if test_type == "level_up":
                cursor.execute(
                    """
                    SELECT MAX(attempt_number) AS max_attempt
                    FROM quiz_sessions
                    WHERE user_id = %s AND test_type = 'level_up'
                    """,
                    (g.user_id,)
                )
                row = cursor.fetchone()
                attempt_number = (row["max_attempt"] or 0) + 1

            # --- FIFO cleanup BEFORE creating new session ---
            if test_type == "level_up":
                cleanup_level_up_sessions(conn, g.user_id)
            elif test_type == "skill_test":
                cleanup_skill_test_session(conn, g.user_id, skill_id)

            # --- Call AI to generate questions ---
            if test_type == "placement":
                questions_data = generate_placement_questions(dream, academics)
            else:
                questions_data = generate_test_questions(
                    dream, academics, current_level, test_type, skill_name
                )

            if not isinstance(questions_data, list) or len(questions_data) == 0:
                return jsonify({"error": "AI did not return valid questions. Please try again."}), 500

            # --- Create quiz_session ---
            cursor.execute(
                """
                INSERT INTO quiz_sessions (user_id, test_type, level, skill_id, attempt_number)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (g.user_id, test_type, current_level, skill_id, attempt_number)
            )
            session_id = cursor.lastrowid

            # --- Insert questions ---
            question_ids = []
            for q in questions_data:
                options_json = None
                correct_answer = None

                if q.get("question_type") == "mcq":
                    import json
                    options_json   = json.dumps(q.get("options") or [])
                    correct_answer = q.get("correct_answer")

                cursor.execute(
                    """
                    INSERT INTO quiz_questions
                        (session_id, question_text, question_type, options, correct_answer, question_number)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        session_id,
                        q.get("question_text", ""),
                        q.get("question_type", "theory"),
                        options_json,
                        correct_answer,
                        q.get("question_number", 0),
                    )
                )
                question_ids.append(cursor.lastrowid)

            # --- Fetch inserted questions to return to frontend ---
            # We deliberately exclude correct_answer so the student cannot
            # see answers in the API response.
            format_qs = []
            for i, q in enumerate(questions_data):
                import json as _json
                format_qs.append({
                    "id":              question_ids[i],
                    "question_number": q.get("question_number"),
                    "question_text":   q.get("question_text"),
                    "question_type":   q.get("question_type"),
                    "options":         q.get("options") if q.get("question_type") == "mcq" else None,
                })

        return jsonify({
            "session_id":  session_id,
            "test_type":   test_type,
            "level":       current_level,
            "questions":   format_qs,
        }), 201

    except Exception as e:
        print(f"[quiz/start] error: {e}")
        return jsonify({"error": "Could not start quiz. Please try again."}), 500

    finally:
        conn.close()


# ============================================================
# POST /api/quiz/submit
# ============================================================
@quiz_bp.route("/quiz/submit", methods=["POST"])
@token_required
def submit_quiz():
    """
    Save the student's answers for a quiz session.

    Expected JSON body:
        {
          "session_id": 7,
          "answers": [
            {"question_id": 101, "answer_text": "B"},
            {"question_id": 102, "answer_text": "A recursive function calls itself."}
          ]
        }

    Validation:
      - session_id must exist and belong to g.user_id
      - answers must be a non-empty list
      - every question_id must belong to that session
      - each answer_text must be a non-empty string

    On success (201):
        { "message": "Answers saved", "session_id": 7 }

    The frontend should immediately call POST /api/grading/run after
    receiving this response.
    """
    data       = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    answers    = data.get("answers")

    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    if not isinstance(answers, list) or len(answers) == 0:
        return jsonify({"error": "answers must be a non-empty list"}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

            # Verify the session exists and belongs to this user
            cursor.execute(
                "SELECT id FROM quiz_sessions WHERE id = %s AND user_id = %s",
                (session_id, g.user_id)
            )
            if not cursor.fetchone():
                return jsonify({"error": "Session not found"}), 404

            # Verify every question_id belongs to this session
            cursor.execute(
                "SELECT id FROM quiz_questions WHERE session_id = %s",
                (session_id,)
            )
            valid_ids = {row["id"] for row in cursor.fetchall()}

            rows_to_insert = []
            for i, ans in enumerate(answers):
                q_id       = ans.get("question_id")
                ans_text   = (ans.get("answer_text") or "").strip()

                if not q_id:
                    return jsonify({"error": f"answers[{i}].question_id is required"}), 400
                if q_id not in valid_ids:
                    return jsonify({"error": f"question_id {q_id} does not belong to this session"}), 400
                if not ans_text:
                    return jsonify({"error": f"answers[{i}].answer_text must not be empty"}), 400

                rows_to_insert.append((session_id, q_id, ans_text))

            # Delete any previous answers for this session (idempotent
            # re-submit safety) before inserting the new ones.
            cursor.execute(
                "DELETE FROM quiz_answers WHERE session_id = %s",
                (session_id,)
            )
            cursor.executemany(
                "INSERT INTO quiz_answers (session_id, question_id, answer_text) VALUES (%s, %s, %s)",
                rows_to_insert
            )

        return jsonify({"message": "Answers saved", "session_id": session_id}), 201

    except Exception as e:
        print(f"[quiz/submit] error: {e}")
        return jsonify({"error": "Could not save answers"}), 500

    finally:
        conn.close()