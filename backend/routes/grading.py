"""
routes/grading.py
"""

import json
from flask import Blueprint, request, jsonify, g

from config.db import get_db_connection
from utils.auth import token_required
from services.groq_service import grade_answers, decide_placement_level

grading_bp = Blueprint("grading", __name__)


@grading_bp.route("/grading/run", methods=["POST"])
@token_required
def run_grading():
    data       = request.get_json(silent=True) or {}
    session_id = data.get("session_id")

    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT qs.id, qs.test_type, qs.level, qs.skill_id
                FROM quiz_sessions qs
                WHERE qs.id = %s AND qs.user_id = %s
                """,
                (session_id, g.user_id)
            )
            session = cursor.fetchone()
            if not session:
                return jsonify({"error": "Session not found"}), 404

            test_type = session["test_type"]
            level     = session["level"]

            cursor.execute(
                """
                SELECT id, question_number, question_text, question_type,
                       options, correct_answer
                FROM quiz_questions
                WHERE session_id = %s
                ORDER BY question_number ASC
                """,
                (session_id,)
            )
            questions_rows = cursor.fetchall()

            cursor.execute(
                "SELECT question_id, answer_text FROM quiz_answers WHERE session_id = %s",
                (session_id,)
            )
            answers_map = {row["question_id"]: row["answer_text"] for row in cursor.fetchall()}

            if not questions_rows:
                return jsonify({"error": "No questions found for this session"}), 422

            if not answers_map:
                return jsonify({"error": "No answers found - submit answers first"}), 422

        questions_for_ai = []
        for q in questions_rows:
            questions_for_ai.append({
                "question_number": q["question_number"],
                "question_text":   q["question_text"],
                "question_type":   q["question_type"],
                "correct_answer":  q["correct_answer"],
            })

        answers_for_ai = []
        for q in questions_rows:
            answers_for_ai.append({
                "question_number": q["question_number"],
                "answer_text":     answers_map.get(q["id"], ""),
            })

        try:
            grading_result = grade_answers(questions_for_ai, answers_for_ai)
        except Exception as e:
            print(f"[grading/run] grade_answers error: {e}")
            return jsonify({"error": "AI grading failed. Please try again."}), 500

        total_score_percent = grading_result.get("total_score_percent", 0.0)
        knowledge_gaps      = grading_result.get("knowledge_gaps", [])
        ai_results          = grading_result.get("results", [])
        ai_results_map      = {r["question_number"]: r for r in ai_results}

        conn2 = get_db_connection()
        try:
            with conn2.cursor() as cursor:
                for q in questions_rows:
                    ai_r = ai_results_map.get(q["question_number"], {})
                    cursor.execute(
                        """
                        INSERT INTO quiz_scores (session_id, question_id, score_out_of_10, feedback)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (session_id, question_id) DO UPDATE SET
                            score_out_of_10 = EXCLUDED.score_out_of_10,
                            feedback        = EXCLUDED.feedback
                        """,
                        (
                            session_id,
                            q["id"],
                            ai_r.get("score_out_of_10", 0),
                            ai_r.get("feedback", ""),
                        )
                    )

                placement_data = None
                if test_type == "placement":

                    cursor.execute(
                        "SELECT dream_career FROM student_profiles WHERE user_id = %s",
                        (g.user_id,)
                    )
                    profile  = cursor.fetchone()
                    dream    = profile["dream_career"] if profile else ""

                    cursor.execute(
                        "SELECT subject, grade, gpa FROM academic_results WHERE user_id = %s",
                        (g.user_id,)
                    )
                    academics = cursor.fetchall()

                    answers_plain = [
                        {
                            "question_text":  q["question_text"],
                            "student_answer": answers_map.get(q["id"], ""),
                        }
                        for q in questions_rows
                    ]
                    scores_plain = [
                        {
                            "question_text":   q["question_text"],
                            "score_out_of_10": ai_results_map.get(q["question_number"], {}).get("score_out_of_10", 0),
                        }
                        for q in questions_rows
                    ]

                    try:
                        placement_result = decide_placement_level(
                            dream, academics, answers_plain, scores_plain
                        )
                    except Exception as e:
                        print(f"[grading/run] decide_placement_level error: {e}")
                        return jsonify({"error": "Could not determine placement level."}), 500

                    starting_level = placement_result.get("starting_level", 1)
                    reasoning      = placement_result.get("reasoning", "")

                    cursor.execute(
                        "SELECT id FROM skill_levels WHERE user_id = %s AND career = %s",
                        (g.user_id, dream)
                    )
                    if cursor.fetchone():
                        cursor.execute(
                            """
                            UPDATE skill_levels SET current_level = %s
                            WHERE user_id = %s AND career = %s
                            """,
                            (starting_level, g.user_id, dream)
                        )
                    else:
                        cursor.execute(
                            """
                            INSERT INTO skill_levels (user_id, career, current_level)
                            VALUES (%s, %s, %s)
                            """,
                            (g.user_id, dream, starting_level)
                        )

                    placement_data = {
                        "starting_level": starting_level,
                        "reasoning":      reasoning,
                    }

        finally:
            conn2.close()

        results_out = []
        for q in questions_rows:
            ai_r = ai_results_map.get(q["question_number"], {})
            results_out.append({
                "question_number": q["question_number"],
                "question_text":   q["question_text"],
                "question_type":   q["question_type"],
                "student_answer":  answers_map.get(q["id"], ""),
                "correct_answer":  q["correct_answer"],
                "score_out_of_10": ai_r.get("score_out_of_10", 0),
                "feedback":        ai_r.get("feedback", ""),
            })

        response = {
            "session_id":          session_id,
            "test_type":           test_type,
            "level":               level,
            "total_score_percent": total_score_percent,
            "knowledge_gaps":      knowledge_gaps,
            "results":             results_out,
        }

        if placement_data:
            response["placement"] = placement_data

        return jsonify(response), 200

    except Exception as e:
        print(f"[grading/run] unexpected error: {e}")
        import traceback; print(traceback.format_exc())
        return jsonify({"error": "Grading failed unexpectedly"}), 500

    finally:
        conn.close()