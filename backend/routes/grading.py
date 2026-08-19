"""
routes/grading.py
-----------------
Grades answers, returns concept-level performance, runs gap analysis,
and creates learner-specific remediation subskills when needed.
"""

from flask import Blueprint, request, jsonify, g

from config.db import get_db_connection
from utils.auth import token_required
from services.groq_service import (
    grade_answers,
    decide_placement_level,
    generate_personalized_subskills,
)
from services.gap_analysis import analyze_skill_gaps

grading_bp = Blueprint("grading", __name__)


@grading_bp.route("/grading/run", methods=["POST"])
@token_required
def run_grading():
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")

    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    qs.id,
                    qs.test_type,
                    qs.level,
                    qs.skill_id,
                    qs.adaptive_skill_id
                FROM quiz_sessions qs
                WHERE qs.id = %s AND qs.user_id = %s
                """,
                (session_id, g.user_id),
            )
            session = cursor.fetchone()

            if not session:
                return jsonify({"error": "Session not found"}), 404

            test_type = session["test_type"]
            level = session["level"]
            skill_id = session["skill_id"]
            adaptive_skill_id = session["adaptive_skill_id"]

            cursor.execute(
                """
                SELECT
                    id,
                    question_number,
                    question_text,
                    question_type,
                    options,
                    correct_answer,
                    concept
                FROM quiz_questions
                WHERE session_id = %s
                ORDER BY question_number ASC
                """,
                (session_id,),
            )
            questions_rows = cursor.fetchall()

            cursor.execute(
                """
                SELECT question_id, answer_text
                FROM quiz_answers
                WHERE session_id = %s
                """,
                (session_id,),
            )
            answers_map = {
                row["question_id"]: row["answer_text"]
                for row in cursor.fetchall()
            }

            if not questions_rows:
                return jsonify({"error": "No questions found for this session"}), 422

            if not answers_map:
                return jsonify({
                    "error": "No answers found - submit answers first"
                }), 422

        questions_for_ai = [
            {
                "question_number": question["question_number"],
                "question_text": question["question_text"],
                "question_type": question["question_type"],
                "correct_answer": question["correct_answer"],
                "concept": question["concept"],
            }
            for question in questions_rows
        ]

        answers_for_ai = [
            {
                "question_number": question["question_number"],
                "answer_text": answers_map.get(question["id"], ""),
            }
            for question in questions_rows
        ]

        try:
            grading_result = grade_answers(
                questions_for_ai,
                answers_for_ai,
            )
        except Exception as error:
            print(f"[grading/run] grade_answers error: {error}")
            return jsonify({
                "error": "AI grading failed. Please try again."
            }), 500

        total_score_percent = grading_result.get(
            "total_score_percent",
            0.0,
        )
        knowledge_gaps = grading_result.get("knowledge_gaps", [])
        concept_performance = grading_result.get(
            "concept_performance",
            [],
        )
        ai_results = grading_result.get("results", [])
        ai_results_map = {
            result["question_number"]: result
            for result in ai_results
        }

        gap_data = None
        placement_data = None
        personalized_subskills = []

        with conn.cursor() as cursor:
            for question in questions_rows:
                ai_result = ai_results_map.get(
                    question["question_number"],
                    {},
                )

                cursor.execute(
                    """
                    INSERT INTO quiz_scores
                        (session_id, question_id, score_out_of_10, feedback)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (session_id, question_id)
                    DO UPDATE SET
                        score_out_of_10 = EXCLUDED.score_out_of_10,
                        feedback = EXCLUDED.feedback
                    """,
                    (
                        session_id,
                        question["id"],
                        ai_result.get("score_out_of_10", 0),
                        ai_result.get("feedback", ""),
                    ),
                )

            # Analyze all skill tests using your existing gap_analysis.py.
            if test_type == "skill_test" and skill_id:
                try:
                    gap_data = analyze_skill_gaps(
                        conn=conn,
                        user_id=g.user_id,
                        skill_id=skill_id,
                        session_id=session_id,
                        questions_rows=questions_rows,
                        ai_results_map=ai_results_map,
                        overall_score=total_score_percent,
                    )
                except Exception as error:
                    import traceback
                    print(f"[grading/run] gap analysis error: {error}")
                    print(traceback.format_exc())

            # Passing a remediation test completes only that remediation skill.
            if (
                test_type == "skill_test"
                and adaptive_skill_id
                and total_score_percent >= 80
            ):
                cursor.execute(
                    """
                    UPDATE adaptive_skills
                    SET status = 'learned'
                    WHERE id = %s AND user_id = %s
                    """,
                    (adaptive_skill_id, g.user_id),
                )

            # A failed core-skill test can create learner-specific subskills.
            if (
                test_type == "skill_test"
                and skill_id
                and not adaptive_skill_id
            ):
                weak_concepts = [
                    item for item in concept_performance
                    if item["score_percent"] < 50
                ]

                if weak_concepts:
                    cursor.execute(
                        """
                        SELECT skill_name, category, skill_type
                        FROM skill_tree
                        WHERE id = %s AND user_id = %s
                        """,
                        (skill_id, g.user_id),
                    )
                    parent_core_skill = cursor.fetchone()

                    if parent_core_skill:
                        try:
                            generated_subskills = (
                                generate_personalized_subskills(
                                    dict(parent_core_skill),
                                    concept_performance,
                                )
                            )

                            for subskill in generated_subskills:
                                cursor.execute(
                                    """
                                    INSERT INTO adaptive_skills
                                        (user_id, parent_skill_id, concept,
                                         skill_name, skill_type, reason, status)
                                    VALUES (%s, %s, %s, %s, %s, %s, 'unlocked')
                                    ON CONFLICT (user_id, parent_skill_id, concept)
                                    WHERE concept IS NOT NULL
                                    DO NOTHING
                                    RETURNING id, concept, skill_name,
                                              skill_type, reason, status
                                    """,
                                    (
                                        g.user_id,
                                        skill_id,
                                        subskill["concept"],
                                        subskill["skill_name"],
                                        subskill.get("skill_type", "mixed"),
                                        subskill["reason"],
                                    ),
                                )
                                created = cursor.fetchone()
                                if created:
                                    personalized_subskills.append(created)

                        except Exception as error:
                            import traceback
                            print(
                                "[grading/run] personalized subskills error: "
                                f"{error}"
                            )
                            print(traceback.format_exc())

            # Placement remains personalized.
            if test_type == "placement":
                cursor.execute(
                    """
                    SELECT dream_career
                    FROM student_profiles
                    WHERE user_id = %s
                    """,
                    (g.user_id,),
                )
                profile = cursor.fetchone()
                dream = profile["dream_career"] if profile else ""

                cursor.execute(
                    """
                    SELECT subject, grade, gpa
                    FROM academic_results
                    WHERE user_id = %s
                    """,
                    (g.user_id,),
                )
                academics = cursor.fetchall()

                answers_plain = [
                    {
                        "question_text": question["question_text"],
                        "student_answer": answers_map.get(question["id"], ""),
                    }
                    for question in questions_rows
                ]

                scores_plain = [
                    {
                        "question_text": question["question_text"],
                        "score_out_of_10": ai_results_map.get(
                            question["question_number"],
                            {},
                        ).get("score_out_of_10", 0),
                    }
                    for question in questions_rows
                ]

                try:
                    placement_result = decide_placement_level(
                        dream,
                        academics,
                        answers_plain,
                        scores_plain,
                    )
                except Exception as error:
                    print(
                        "[grading/run] decide_placement_level error: "
                        f"{error}"
                    )
                    return jsonify({
                        "error": "Could not determine placement level."
                    }), 500

                starting_level = placement_result.get("starting_level", 1)
                reasoning = placement_result.get("reasoning", "")

                cursor.execute(
                    """
                    SELECT id
                    FROM skill_levels
                    WHERE user_id = %s AND career = %s
                    """,
                    (g.user_id, dream),
                )

                if cursor.fetchone():
                    cursor.execute(
                        """
                        UPDATE skill_levels
                        SET current_level = %s
                        WHERE user_id = %s AND career = %s
                        """,
                        (starting_level, g.user_id, dream),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO skill_levels
                            (user_id, career, current_level)
                        VALUES (%s, %s, %s)
                        """,
                        (g.user_id, dream, starting_level),
                    )

                placement_data = {
                    "starting_level": starting_level,
                    "reasoning": reasoning,
                }

        results_out = []

        for question in questions_rows:
            ai_result = ai_results_map.get(
                question["question_number"],
                {},
            )
            results_out.append({
                "question_number": question["question_number"],
                "question_text": question["question_text"],
                "question_type": question["question_type"],
                "concept": question["concept"],
                "student_answer": answers_map.get(question["id"], ""),
                "correct_answer": question["correct_answer"],
                "score_out_of_10": ai_result.get("score_out_of_10", 0),
                "feedback": ai_result.get("feedback", ""),
            })

        response = {
            "session_id": session_id,
            "test_type": test_type,
            "level": level,
            "total_score_percent": total_score_percent,
            "knowledge_gaps": knowledge_gaps,
            "concept_performance": concept_performance,
            "personalized_subskills": personalized_subskills,
            "results": results_out,
        }

        if placement_data:
            response["placement"] = placement_data

        if gap_data:
            response["gap_analysis"] = gap_data

        return jsonify(response), 200

    except Exception as error:
        import traceback
        print(f"[grading/run] unexpected error: {error}")
        print(traceback.format_exc())
        return jsonify({"error": "Grading failed unexpectedly"}), 500

    finally:
        conn.close()