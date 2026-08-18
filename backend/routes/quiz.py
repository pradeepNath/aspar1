"""
routes/quiz.py
---------------
UPDATED:
1. Saves the "concept" field on each question (for gap analysis)
2. Passes skill_type to generate_test_questions() for skill tests
   (adjusts question style: math skills get calculation questions,
   practical skills get scenario questions, etc.)
"""

from flask import Blueprint, request, jsonify, g
import json

from config.db import get_db_connection
from utils.auth import token_required
from services.groq_service import generate_placement_questions, generate_test_questions
from services.fifo_service import cleanup_level_up_sessions, cleanup_skill_test_session

quiz_bp = Blueprint("quiz", __name__)


@quiz_bp.route("/quiz/start", methods=["POST"])
@token_required
def start_quiz():
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

            cursor.execute(
                "SELECT current_level FROM skill_levels WHERE user_id = %s AND career = %s",
                (g.user_id, dream)
            )
            level_row = cursor.fetchone()
            current_level = level_row["current_level"] if level_row else 1

            # --- 4-hour cooldown check for skill tests ---
            skill_name = None
            skill_type = None
            if test_type == "skill_test":
                cursor.execute(
                    "SELECT skill_name, skill_type, level FROM skill_tree WHERE id = %s AND user_id = %s",
                    (skill_id, g.user_id)
                )
                skill_row = cursor.fetchone()
                if not skill_row:
                    return jsonify({"error": "Skill not found"}), 404
                skill_name    = skill_row["skill_name"]
                skill_type    = skill_row["skill_type"]
                current_level = skill_row["level"]

                # Check cooldown from last_attempt_log
                cursor.execute(
                    "SELECT last_attempt_at FROM last_attempt_log WHERE user_id = %s AND skill_id = %s",
                    (g.user_id, skill_id)
                )
                attempt_row = cursor.fetchone()
                if attempt_row:
                    from datetime import datetime, timezone, timedelta
                    last_attempt = attempt_row["last_attempt_at"]
                    if last_attempt.tzinfo is None:
                        last_attempt = last_attempt.replace(tzinfo=timezone.utc)
                    elapsed   = datetime.now(timezone.utc) - last_attempt
                    remaining = timedelta(hours=4) - elapsed
                    if remaining.total_seconds() > 0:
                        minutes_left = int(remaining.total_seconds() / 60)
                        return jsonify({
                            "error": f"Please wait {minutes_left} more minute(s) before retrying this skill test."
                        }), 429

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

            if test_type == "level_up":
                cleanup_level_up_sessions(conn, g.user_id)
            elif test_type == "skill_test":
                cleanup_skill_test_session(conn, g.user_id, skill_id)

            # --- Generate questions ---
            if test_type == "placement":
                questions_data = generate_placement_questions(dream, academics)
            else:
                questions_data = generate_test_questions(
                    dream, academics, current_level, test_type, skill_name, skill_type
                )

            if not isinstance(questions_data, list) or len(questions_data) == 0:
                return jsonify({"error": "AI did not return valid questions. Please try again."}), 500

            cursor.execute(
                """
                INSERT INTO quiz_sessions (user_id, test_type, level, skill_id, attempt_number)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (g.user_id, test_type, current_level, skill_id, attempt_number)
            )
            session_id = cursor.fetchone()["id"]

            # --- Insert questions WITH concept field ---
            question_ids = []
            for q in questions_data:
                options_json   = None
                correct_answer = None
                if q.get("question_type") == "mcq":
                    options_json   = json.dumps(q.get("options") or [])
                    correct_answer = q.get("correct_answer")

                cursor.execute(
                    """
                    INSERT INTO quiz_questions
                        (session_id, question_text, question_type, options,
                         correct_answer, question_number, concept)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        session_id,
                        q.get("question_text", ""),
                        q.get("question_type", "theory"),
                        options_json,
                        correct_answer,
                        q.get("question_number", 0),
                        q.get("concept", "General"),
                    )
                )
                question_ids.append(cursor.fetchone()["id"])

            # --- Record this attempt for cooldown tracking ---
            if test_type == "skill_test":
                cursor.execute(
                    """
                    INSERT INTO last_attempt_log (user_id, skill_id, last_attempt_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (user_id, skill_id) DO UPDATE SET
                        last_attempt_at = NOW()
                    """,
                    (g.user_id, skill_id)
                )

            format_qs = []
            for i, q in enumerate(questions_data):
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
        import traceback
        print(f"[quiz/start] error: {e}")
        print(traceback.format_exc())
        return jsonify({"error": "Could not start quiz. Please try again."}), 500

    finally:
        conn.close()


@quiz_bp.route("/quiz/submit", methods=["POST"])
@token_required
def submit_quiz():
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

            cursor.execute(
                "SELECT id FROM quiz_sessions WHERE id = %s AND user_id = %s",
                (session_id, g.user_id)
            )
            if not cursor.fetchone():
                return jsonify({"error": "Session not found"}), 404

            cursor.execute(
                "SELECT id FROM quiz_questions WHERE session_id = %s",
                (session_id,)
            )
            valid_ids = {row["id"] for row in cursor.fetchall()}

            rows_to_insert = []
            for i, ans in enumerate(answers):
                q_id     = ans.get("question_id")
                ans_text = (ans.get("answer_text") or "").strip()

                if not q_id:
                    return jsonify({"error": f"answers[{i}].question_id is required"}), 400
                if q_id not in valid_ids:
                    return jsonify({"error": f"question_id {q_id} does not belong to this session"}), 400
                if not ans_text:
                    return jsonify({"error": f"answers[{i}].answer_text must not be empty"}), 400

                rows_to_insert.append((session_id, q_id, ans_text))

            cursor.execute("DELETE FROM quiz_answers WHERE session_id = %s", (session_id,))
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