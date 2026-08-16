"""
routes/grading.py
------------------
Handles AI grading and post-grading logic:

    POST /api/grading/run
        - Loads questions + answers from DB for a session
        - Calls grade_answers() (AI function 5)
        - Saves per-question scores + feedback to quiz_scores
        - If test_type == "placement": calls decide_placement_level()
          (AI function 2) and writes the starting level to skill_levels
        - Returns full grading results + (for placement) starting level

The route is intentionally SEPARATE from quiz/submit so the frontend can
show a "grading in progress" loading screen between submit and results,
and so grading can be retried independently if the AI call fails.
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
    """
    Trigger AI grading for a submitted quiz session.

    Expected JSON body:
        { "session_id": 7 }

    Flow:
        1. Verify session belongs to g.user_id
        2. Load questions (with correct_answer) + student answers from DB
        3. Call grade_answers() -> scores, feedback, knowledge_gaps
        4. Save scores to quiz_scores
        5. If placement: call decide_placement_level() -> save to skill_levels
        6. Return full results

    On success (200):
        {
          "session_id": 7,
          "test_type": "placement",
          "total_score_percent": 75.0,
          "knowledge_gaps": ["Recursion", "Big-O notation"],
          "results": [
            {
              "question_number": 1,
              "question_text": "...",
              "student_answer": "B",
              "correct_answer": "B",     # null for theory
              "score_out_of_10": 10,
              "feedback": "Correct!"
            },
            ...
          ],
          // only present for placement test:
          "placement": {
            "starting_level": 2,
            "reasoning": "..."
          }
        }
    """
    data       = request.get_json(silent=True) or {}
    session_id = data.get("session_id")

    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

            # --- Verify session ownership ---
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

            # --- Load questions (including correct_answer for grading) ---
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

            # --- Load student answers keyed by question_id ---
            cursor.execute(
                "SELECT question_id, answer_text FROM quiz_answers WHERE session_id = %s",
                (session_id,)
            )
            answers_map = {row["question_id"]: row["answer_text"] for row in cursor.fetchall()}

            if not questions_rows:
                return jsonify({"error": "No questions found for this session"}), 422

            if not answers_map:
                return jsonify({"error": "No answers found - submit answers first"}), 422

        # --- Build structures for grade_answers() ---
        questions_for_ai = []
        for q in questions_rows:
            questions_for_ai.append({
                "question_number": q["question_number"],
                "question_text":   q["question_text"],
                "question_type":   q["question_type"],
                "correct_answer":  q["correct_answer"],  # included for MCQ grading
            })

        answers_for_ai = []
        for q in questions_rows:
            answers_for_ai.append({
                "question_number": q["question_number"],
                "answer_text":     answers_map.get(q["id"], ""),
            })

        # --- AI grading call (function 5) ---
        try:
            grading_result = grade_answers(questions_for_ai, answers_for_ai)
        except Exception as e:
            print(f"[grading/run] grade_answers error: {e}")
            return jsonify({"error": "AI grading failed. Please try again."}), 500

        total_score_percent = grading_result.get("total_score_percent", 0.0)
        knowledge_gaps      = grading_result.get("knowledge_gaps", [])
        ai_results          = grading_result.get("results", [])

        # Build a map: question_number -> ai result for easy lookup
        ai_results_map = {r["question_number"]: r for r in ai_results}

        # --- Save scores to quiz_scores ---
        conn2 = get_db_connection()
        try:
            with conn2.cursor() as cursor:
                for q in questions_rows:
                    ai_r = ai_results_map.get(q["question_number"], {})
                    cursor.execute(
                        """
                        INSERT INTO quiz_scores (session_id, question_id, score_out_of_10, feedback)
                        VALUES (%s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            score_out_of_10 = VALUES(score_out_of_10),
                            feedback        = VALUES(feedback)
                        """,
                        (
                            session_id,
                            q["id"],
                            ai_r.get("score_out_of_10", 0),
                            ai_r.get("feedback", ""),
                        )
                    )

                # --- Placement: decide starting level (AI function 2) ---
                placement_data = None
                if test_type == "placement":

                    # Fetch student context for decide_placement_level
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

                    # Upsert into skill_levels
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

        # --- Build response ---
        results_out = []
        for q in questions_rows:
            ai_r = ai_results_map.get(q["question_number"], {})
            results_out.append({
                "question_number": q["question_number"],
                "question_text":   q["question_text"],
                "question_type":   q["question_type"],
                "student_answer":  answers_map.get(q["id"], ""),
                # Reveal correct_answer in results so student can see
                # what the right answer was after grading.
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
        return jsonify({"error": "Grading failed unexpectedly"}), 500

    finally:
        conn.close()