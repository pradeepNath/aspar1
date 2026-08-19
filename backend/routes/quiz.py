"""
routes/quiz.py
---------------
Creates placement, level-up, core-skill, and personalized-subskill quizzes.

For a personalized subskill:
- quiz_sessions.skill_id keeps the parent core-skill ID
- quiz_sessions.adaptive_skill_id identifies the remediation subskill
- grading.py marks that adaptive skill learned after an 80%+ result
"""

import json
import re
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify, g

from config.db import get_db_connection
from utils.auth import token_required
from services.groq_service import (
    generate_placement_questions,
    generate_test_questions,
)
from services.fifo_service import (
    cleanup_level_up_sessions,
    cleanup_skill_test_session,
)

quiz_bp = Blueprint("quiz", __name__)


@quiz_bp.route("/quiz/start", methods=["POST"])
@token_required
def start_quiz():
    data = request.get_json(silent=True) or {}

    test_type = (data.get("test_type") or "").strip()
    skill_id = data.get("skill_id")
    adaptive_skill_id = data.get("adaptive_skill_id")

    if test_type not in ("placement", "level_up", "skill_test"):
        return jsonify({
            "error": (
                "test_type must be placement, level_up, or skill_test"
            )
        }), 400

    if test_type == "skill_test" and not skill_id and not adaptive_skill_id:
        return jsonify({
            "error": (
                "skill_id or adaptive_skill_id is required for skill_test"
            )
        }), 400

    if test_type != "skill_test" and adaptive_skill_id:
        return jsonify({
            "error": "adaptive_skill_id is only valid for skill_test"
        }), 400

    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT dream_career
                FROM student_profiles
                WHERE user_id = %s
                """,
                (g.user_id,),
            )
            profile = cursor.fetchone()

            if not profile:
                return jsonify({
                    "error": "Please set your dream career first"
                }), 422

            dream = profile["dream_career"]

            cursor.execute(
                """
                SELECT subject, grade, gpa
                FROM academic_results
                WHERE user_id = %s
                """,
                (g.user_id,),
            )
            academics = cursor.fetchall()

            cursor.execute(
                """
                SELECT current_level
                FROM skill_levels
                WHERE user_id = %s AND career = %s
                """,
                (g.user_id, dream),
            )
            level_row = cursor.fetchone()
            current_level = (
                level_row["current_level"] if level_row else 1
            )

            skill_name = None
            skill_type = None
            parent_skill_id = None
            is_adaptive_quiz = False

            # ── Personalized remediation subskill quiz ────────────────
            if test_type == "skill_test" and adaptive_skill_id:
                cursor.execute(
                    """
                    SELECT
                        a.id,
                        a.skill_name,
                        a.skill_type,
                        a.status,
                        a.parent_skill_id,
                        st.level,
                        st.career
                    FROM adaptive_skills a
                    JOIN skill_tree st ON st.id = a.parent_skill_id
                    WHERE a.id = %s
                      AND a.user_id = %s
                    """,
                    (adaptive_skill_id, g.user_id),
                )
                adaptive_skill = cursor.fetchone()

                if not adaptive_skill:
                    return jsonify({
                        "error": "Personalized subskill not found"
                    }), 404

                if adaptive_skill["status"] == "learned":
                    return jsonify({
                        "error": "This personalized subskill is already learned"
                    }), 409

                skill_name = adaptive_skill["skill_name"]
                skill_type = adaptive_skill["skill_type"] or "mixed"
                parent_skill_id = adaptive_skill["parent_skill_id"]
                current_level = adaptive_skill["level"]
                skill_id = parent_skill_id
                is_adaptive_quiz = True

            # ── Normal standardized core-skill quiz ───────────────────
            elif test_type == "skill_test":
                cursor.execute(
                    """
                    SELECT id, skill_name, skill_type, level, status
                    FROM skill_tree
                    WHERE id = %s AND user_id = %s
                    """,
                    (skill_id, g.user_id),
                )
                skill_row = cursor.fetchone()

                if not skill_row:
                    return jsonify({"error": "Skill not found"}), 404

                if skill_row["status"] != "unlocked":
                    return jsonify({
                        "error": "This core skill is not unlocked yet"
                    }), 409

                skill_name = skill_row["skill_name"]
                skill_type = skill_row["skill_type"] or "mixed"
                current_level = skill_row["level"]
                parent_skill_id = skill_id

                # Core-skill retake cooldown.
                cursor.execute(
                    """
                    SELECT last_attempt_at
                    FROM last_attempt_log
                    WHERE user_id = %s AND skill_id = %s
                    """,
                    (g.user_id, skill_id),
                )
                attempt_row = cursor.fetchone()

                if attempt_row:
                    last_attempt = attempt_row["last_attempt_at"]

                    if last_attempt.tzinfo is None:
                        last_attempt = last_attempt.replace(
                            tzinfo=timezone.utc
                        )

                    elapsed = datetime.now(timezone.utc) - last_attempt
                    remaining = timedelta(hours=0) - elapsed

                    if remaining.total_seconds() > 0:
                        minutes_left = int(
                            remaining.total_seconds() / 60
                        )
                        return jsonify({
                            "error": (
                                f"Please wait {minutes_left} more minute(s) "
                                "before retrying this skill test."
                            )
                        }), 429

            # ── Attempt number for level-up tests ─────────────────────
            attempt_number = 1

            if test_type == "level_up":
                cursor.execute(
                    """
                    SELECT MAX(attempt_number) AS max_attempt
                    FROM quiz_sessions
                    WHERE user_id = %s
                      AND test_type = 'level_up'
                    """,
                    (g.user_id,),
                )
                row = cursor.fetchone()
                attempt_number = (row["max_attempt"] or 0) + 1

                cleanup_level_up_sessions(conn, g.user_id)

            # Keep your existing FIFO cleanup for normal core-skill tests.
            elif test_type == "skill_test" and not is_adaptive_quiz:
                cleanup_skill_test_session(conn, g.user_id, skill_id)

            # ── Generate questions ────────────────────────────────────
            if test_type == "placement":
                questions_data = generate_placement_questions(
                    dream,
                    academics,
                )
                # Difficulty is used internally for placement. Never expose
                # it to learners in the question wording.
                for question in questions_data:
                    question["question_text"] = re.sub(
                        r"^\s*level\s*[1-3]\s*:\s*",
                        "",
                        question.get("question_text", ""),
                        flags=re.IGNORECASE,
                    )
            else:
                questions_data = generate_test_questions(
                    dream,
                    academics,
                    current_level,
                    test_type,
                    skill_name,
                    skill_type,
                )

            if (
                not isinstance(questions_data, list)
                or len(questions_data) == 0
            ):
                return jsonify({
                    "error": "AI did not return valid questions. Please try again."
                }), 500

            cursor.execute(
                """
                INSERT INTO quiz_sessions
                    (user_id, test_type, level, skill_id,
                     adaptive_skill_id, attempt_number)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    g.user_id,
                    test_type,
                    current_level,
                    parent_skill_id if test_type == "skill_test" else None,
                    adaptive_skill_id if is_adaptive_quiz else None,
                    attempt_number,
                ),
            )
            session_id = cursor.fetchone()["id"]

            question_ids = []

            for question in questions_data:
                options_json = None
                correct_answer = None

                if question.get("question_type") == "mcq":
                    options_json = json.dumps(
                        question.get("options") or []
                    )
                    correct_answer = question.get("correct_answer")

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
                        question.get("question_text", ""),
                        question.get("question_type", "theory"),
                        options_json,
                        correct_answer,
                        question.get("question_number", 0),
                        question.get("concept", "General"),
                    ),
                )
                question_ids.append(cursor.fetchone()["id"])

            # Keep the cooldown only for normal core-skill tests.
            if test_type == "skill_test" and not is_adaptive_quiz:
                cursor.execute(
                    """
                    INSERT INTO last_attempt_log
                        (user_id, skill_id, last_attempt_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (user_id, skill_id)
                    DO UPDATE SET last_attempt_at = NOW()
                    """,
                    (g.user_id, skill_id),
                )

            formatted_questions = []

            for index, question in enumerate(questions_data):
                formatted_questions.append({
                    "id": question_ids[index],
                    "question_number": question.get("question_number"),
                    "question_text": question.get("question_text"),
                    "question_type": question.get("question_type"),
                    "options": (
                        question.get("options")
                        if question.get("question_type") == "mcq"
                        else None
                    ),
                })

        return jsonify({
            "session_id": session_id,
            "test_type": test_type,
            "level": current_level,
            "skill_id": parent_skill_id,
            "adaptive_skill_id": (
                adaptive_skill_id if is_adaptive_quiz else None
            ),
            "questions": formatted_questions,
        }), 201

    except Exception as error:
        import traceback
        print(f"[quiz/start] error: {error}")
        print(traceback.format_exc())
        return jsonify({
            "error": "Could not start quiz. Please try again."
        }), 500

    finally:
        conn.close()


@quiz_bp.route("/quiz/submit", methods=["POST"])
@token_required
def submit_quiz():
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    answers = data.get("answers")

    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    if not isinstance(answers, list) or len(answers) == 0:
        return jsonify({
            "error": "answers must be a non-empty list"
        }), 400

    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM quiz_sessions
                WHERE id = %s AND user_id = %s
                """,
                (session_id, g.user_id),
            )

            if not cursor.fetchone():
                return jsonify({"error": "Session not found"}), 404

            cursor.execute(
                """
                SELECT id
                FROM quiz_questions
                WHERE session_id = %s
                """,
                (session_id,),
            )
            valid_question_ids = {
                row["id"] for row in cursor.fetchall()
            }

            rows_to_insert = []

            for index, answer in enumerate(answers):
                question_id = answer.get("question_id")
                answer_text = (answer.get("answer_text") or "").strip()

                if not question_id:
                    return jsonify({
                        "error": (
                            f"answers[{index}].question_id is required"
                        )
                    }), 400

                if question_id not in valid_question_ids:
                    return jsonify({
                        "error": (
                            f"question_id {question_id} "
                            "does not belong to this session"
                        )
                    }), 400

                if not answer_text:
                    return jsonify({
                        "error": (
                            f"answers[{index}].answer_text must not be empty"
                        )
                    }), 400

                rows_to_insert.append(
                    (session_id, question_id, answer_text)
                )

            cursor.execute(
                "DELETE FROM quiz_answers WHERE session_id = %s",
                (session_id,),
            )

            cursor.executemany(
                """
                INSERT INTO quiz_answers
                    (session_id, question_id, answer_text)
                VALUES (%s, %s, %s)
                """,
                rows_to_insert,
            )

        return jsonify({
            "message": "Answers saved",
            "session_id": session_id,
        }), 201

    except Exception as error:
        print(f"[quiz/submit] error: {error}")
        return jsonify({"error": "Could not save answers"}), 500

    finally:
        conn.close()
