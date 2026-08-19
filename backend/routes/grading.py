"""
routes/grading.py
-----------------
Grades answers, returns concept-level performance, runs gap analysis,
and creates learner-specific remediation subskills when needed.
"""

import json

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
        return jsonify({
            "error": "session_id is required"
        }), 400

    conn = get_db_connection()

    try:

        # ============================================================
        # LOAD QUIZ SESSION
        # ============================================================

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
                WHERE qs.id = %s
                  AND qs.user_id = %s
                """,
                (
                    session_id,
                    g.user_id,
                ),
            )

            session = cursor.fetchone()

            if not session:
                return jsonify({
                    "error": "Session not found"
                }), 404

            test_type = session["test_type"]
            level = session["level"]
            skill_id = session["skill_id"]
            adaptive_skill_id = session["adaptive_skill_id"]

            # ========================================================
            # LOAD QUESTIONS
            # ========================================================

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

            # ========================================================
            # LOAD ANSWERS
            # ========================================================

            cursor.execute(
                """
                SELECT
                    question_id,
                    answer_text
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
                return jsonify({
                    "error": "No questions found for this session"
                }), 422

            if not answers_map:
                return jsonify({
                    "error": "No answers found - submit answers first"
                }), 422

        # ============================================================
        # PREPARE QUESTIONS FOR AI
        # ============================================================

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
                "answer_text": answers_map.get(
                    question["id"],
                    "",
                ),
            }
            for question in questions_rows
        ]

        # ============================================================
        # AI GRADING
        # ============================================================

        try:

            grading_result = grade_answers(
                questions_for_ai,
                answers_for_ai,
            )

        except Exception as error:

            print(
                f"[grading/run] grade_answers error: {error}"
            )

            return jsonify({
                "error": "AI grading failed. Please try again."
            }), 500

        total_score_percent = grading_result.get(
            "total_score_percent",
            0.0,
        )

        knowledge_gaps = grading_result.get(
            "knowledge_gaps",
            [],
        )

        ai_results = grading_result.get(
            "results",
            [],
        )

        ai_results_map = {
            result["question_number"]: result
            for result in ai_results
        }

        # ============================================================
        # VARIABLES
        # ============================================================

        concept_performance = []

        # This will contain only concepts that are weak in the
        # CURRENT attempt.
        current_weak_concepts = []

        # This will contain only concepts that are weak in the
        # CURRENT attempt AND were weak in a PREVIOUS attempt.
        persistent_weak_concepts = []

        gap_data = None
        placement_data = None

        personalized_subskills = []

        # ============================================================
        # SAVE INDIVIDUAL QUESTION SCORES
        # ============================================================

        with conn.cursor() as cursor:

            for question in questions_rows:

                ai_result = ai_results_map.get(
                    question["question_number"],
                    {},
                )

                cursor.execute(
                    """
                    INSERT INTO quiz_scores
                        (
                            session_id,
                            question_id,
                            score_out_of_10,
                            feedback
                        )
                    VALUES
                        (
                            %s,
                            %s,
                            %s,
                            %s
                        )
                    ON CONFLICT
                        (
                            session_id,
                            question_id
                        )
                    DO UPDATE SET
                        score_out_of_10 =
                            EXCLUDED.score_out_of_10,
                        feedback =
                            EXCLUDED.feedback
                    """,
                    (
                        session_id,
                        question["id"],
                        ai_result.get(
                            "score_out_of_10",
                            0,
                        ),
                        ai_result.get(
                            "feedback",
                            "",
                        ),
                    ),
                )

            # ========================================================
            # GAP ANALYSIS
            # ========================================================

            if (
                test_type == "skill_test"
                and skill_id
            ):

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

                    print(
                        "[grading/run] "
                        f"gap analysis error: {error}"
                    )

                    print(
                        traceback.format_exc()
                    )

            # ========================================================
            # CURRENT CONCEPT PERFORMANCE
            # ========================================================

            if gap_data:

                current_weak_concepts = [
                    {
                        "concept": item["concept"],
                        "score_percent": item["score"],
                    }
                    for item in gap_data.get(
                        "weak_concepts",
                        [],
                    )
                ]

                concept_performance = list(
                    current_weak_concepts
                )

            # ========================================================
            # FIND PERSISTENT LEARNING GAPS
            # ========================================================
            #
            # IMPORTANT:
            #
            # A concept being weak ONCE does NOT create a
            # personalized subskill.
            #
            # Example:
            #
            # Attempt 1:
            #   Repository Initialization = 0%
            #
            # Result:
            #   weak concept
            #   NO personalized subskill
            #
            # Attempt 2:
            #   Repository Initialization = 20%
            #
            # Result:
            #   persistent gap
            #   CREATE personalized subskill
            #
            # We use the existing skill_gap_analysis table.
            # ========================================================

            if (
                test_type == "skill_test"
                and skill_id
                and current_weak_concepts
            ):

                try:

                    cursor.execute(
                        """
                        SELECT
                            session_id,
                            weak_concepts
                        FROM skill_gap_analysis
                        WHERE user_id = %s
                          AND skill_id = %s
                          AND session_id <> %s
                        ORDER BY analyzed_at DESC
                        LIMIT 10
                        """,
                        (
                            g.user_id,
                            skill_id,
                            session_id,
                        ),
                    )

                    previous_gap_rows = (
                        cursor.fetchall()
                    )

                    previous_weak_concepts = set()

                    # ------------------------------------------------
                    # Normalize concept names.
                    #
                    # This prevents:
                    #
                    # "Repository Initialization"
                    #
                    # and
                    #
                    # " repository initialization "
                    #
                    # from being treated as different concepts.
                    # ------------------------------------------------

                    def normalize_concept(value):

                        if not value:
                            return ""

                        return " ".join(
                            str(value)
                            .strip()
                            .lower()
                            .split()
                        )

                    # ------------------------------------------------
                    # Extract previous weak concepts
                    # ------------------------------------------------

                    for row in previous_gap_rows:

                        try:

                            old_weak_concepts = (
                                json.loads(
                                    row["weak_concepts"]
                                    or "[]"
                                )
                            )

                            if not isinstance(
                                old_weak_concepts,
                                list,
                            ):
                                continue

                            for item in old_weak_concepts:

                                if isinstance(
                                    item,
                                    dict,
                                ):
                                    concept = item.get(
                                        "concept"
                                    )
                                else:
                                    concept = item

                                normalized = (
                                    normalize_concept(
                                        concept
                                    )
                                )

                                if normalized:

                                    previous_weak_concepts.add(
                                        normalized
                                    )

                        except (
                            TypeError,
                            ValueError,
                            json.JSONDecodeError,
                        ):
                            continue

                    # ------------------------------------------------
                    # Current weak concept + previous weak concept
                    # = persistent gap
                    # ------------------------------------------------

                    for item in current_weak_concepts:

                        concept = item["concept"]

                        normalized = (
                            normalize_concept(
                                concept
                            )
                        )

                        if (
                            normalized
                            in previous_weak_concepts
                        ):

                            persistent_weak_concepts.append(
                                {
                                    "concept": concept,
                                    "score_percent": item[
                                        "score_percent"
                                    ],
                                }
                            )

                except Exception as error:

                    import traceback

                    print(
                        "[grading/run] "
                        "persistent gap detection error: "
                        f"{error}"
                    )

                    print(
                        traceback.format_exc()
                    )

            # ========================================================
            # PERSONALIZED SUBSKILLS
            # ========================================================
            #
            # ONLY persistent gaps reach this section.
            #
            # A single failed question is therefore NOT enough.
            # ========================================================

            if (
                test_type == "skill_test"
                and skill_id
                and not adaptive_skill_id
                and persistent_weak_concepts
            ):

                cursor.execute(
                    """
                    SELECT
                        skill_name,
                        category,
                        skill_type
                    FROM skill_tree
                    WHERE id = %s
                      AND user_id = %s
                    """,
                    (
                        skill_id,
                        g.user_id,
                    ),
                )

                parent_core_skill = (
                    cursor.fetchone()
                )

                if parent_core_skill:

                    try:

                        generated_subskills = (
                            generate_personalized_subskills(
                                dict(
                                    parent_core_skill
                                ),
                                persistent_weak_concepts,
                            )
                        )

                        # ------------------------------------------------
                        # Save generated subskills
                        # ------------------------------------------------

                        for subskill in (
                            generated_subskills
                        ):

                            cursor.execute(
                                """
                                INSERT INTO adaptive_skills
                                    (
                                        user_id,
                                        parent_skill_id,
                                        concept,
                                        skill_name,
                                        skill_type,
                                        reason,
                                        status
                                    )
                                VALUES
                                    (
                                        %s,
                                        %s,
                                        %s,
                                        %s,
                                        %s,
                                        %s,
                                        'unlocked'
                                    )
                                ON CONFLICT
                                    (
                                        user_id,
                                        parent_skill_id,
                                        concept
                                    )
                                WHERE concept IS NOT NULL
                                DO NOTHING
                                RETURNING
                                    id,
                                    concept,
                                    skill_name,
                                    skill_type,
                                    reason,
                                    status
                                """,
                                (
                                    g.user_id,
                                    skill_id,
                                    subskill["concept"],
                                    subskill["skill_name"],
                                    subskill.get(
                                        "skill_type",
                                        "mixed",
                                    ),
                                    subskill["reason"],
                                ),
                            )

                            created = (
                                cursor.fetchone()
                            )

                            if created:

                                personalized_subskills.append(
                                    created
                                )

                    except Exception as error:

                        import traceback

                        print(
                            "[grading/run] "
                            "personalized subskills error: "
                            f"{error}"
                        )

                        print(
                            traceback.format_exc()
                        )

            # ========================================================
            # PLACEMENT TEST
            # ========================================================

            if test_type == "placement":

                cursor.execute(
                    """
                    SELECT
                        dream_career
                    FROM student_profiles
                    WHERE user_id = %s
                    """,
                    (g.user_id,),
                )

                profile = cursor.fetchone()

                dream = (
                    profile["dream_career"]
                    if profile
                    else ""
                )

                cursor.execute(
                    """
                    SELECT
                        subject,
                        grade,
                        gpa
                    FROM academic_results
                    WHERE user_id = %s
                    """,
                    (g.user_id,),
                )

                academics = cursor.fetchall()

                answers_plain = [
                    {
                        "question_text": (
                            question["question_text"]
                        ),
                        "student_answer": (
                            answers_map.get(
                                question["id"],
                                "",
                            )
                        ),
                    }
                    for question in questions_rows
                ]

                scores_plain = [
                    {
                        "question_text": (
                            question["question_text"]
                        ),
                        "score_out_of_10": (
                            ai_results_map.get(
                                question["question_number"],
                                {},
                            ).get(
                                "score_out_of_10",
                                0,
                            )
                        ),
                    }
                    for question in questions_rows
                ]

                try:

                    placement_result = (
                        decide_placement_level(
                            dream,
                            academics,
                            answers_plain,
                            scores_plain,
                        )
                    )

                except Exception as error:

                    print(
                        "[grading/run] "
                        "decide_placement_level error: "
                        f"{error}"
                    )

                    return jsonify({
                        "error": (
                            "Could not determine "
                            "placement level."
                        )
                    }), 500

                starting_level = (
                    placement_result.get(
                        "starting_level",
                        1,
                    )
                )

                reasoning = (
                    placement_result.get(
                        "reasoning",
                        "",
                    )
                )

                cursor.execute(
                    """
                    SELECT id
                    FROM skill_levels
                    WHERE user_id = %s
                      AND career = %s
                    """,
                    (
                        g.user_id,
                        dream,
                    ),
                )

                if cursor.fetchone():

                    cursor.execute(
                        """
                        UPDATE skill_levels
                        SET current_level = %s
                        WHERE user_id = %s
                          AND career = %s
                        """,
                        (
                            starting_level,
                            g.user_id,
                            dream,
                        ),
                    )

                else:

                    cursor.execute(
                        """
                        INSERT INTO skill_levels
                            (
                                user_id,
                                career,
                                current_level
                            )
                        VALUES
                            (
                                %s,
                                %s,
                                %s
                            )
                        """,
                        (
                            g.user_id,
                            dream,
                            starting_level,
                        ),
                    )

                placement_data = {
                    "starting_level": starting_level,
                    "reasoning": reasoning,
                }

        # ============================================================
        # BUILD RESPONSE
        # ============================================================

        results_out = []

        for question in questions_rows:

            ai_result = ai_results_map.get(
                question["question_number"],
                {},
            )

            results_out.append(
                {
                    "question_number": (
                        question["question_number"]
                    ),
                    "question_text": (
                        question["question_text"]
                    ),
                    "question_type": (
                        question["question_type"]
                    ),
                    "concept": (
                        question["concept"]
                    ),
                    "student_answer": (
                        answers_map.get(
                            question["id"],
                            "",
                        )
                    ),
                    "correct_answer": (
                        question["correct_answer"]
                    ),
                    "score_out_of_10": (
                        ai_result.get(
                            "score_out_of_10",
                            0,
                        )
                    ),
                    "feedback": (
                        ai_result.get(
                            "feedback",
                            "",
                        )
                    ),
                }
            )

        # ============================================================
        # FINAL RESPONSE
        # ============================================================

        response = {
            "session_id": session_id,
            "test_type": test_type,
            "level": level,
            "total_score_percent": (
                total_score_percent
            ),
            "knowledge_gaps": knowledge_gaps,

            # Weak concepts in current attempt.
            "concept_performance": (
                concept_performance
            ),

            # Repeated weak concepts.
            "persistent_weak_concepts": (
                persistent_weak_concepts
            ),

            # Newly created personalized subskills.
            "personalized_subskills": (
                personalized_subskills
            ),

            "results": results_out,
        }

        if placement_data:

            response["placement"] = (
                placement_data
            )

        if gap_data:

            response["gap_analysis"] = (
                gap_data
            )

        return jsonify(response), 200

    except Exception as error:

        import traceback

        print(
            "[grading/run] unexpected error: "
            f"{error}"
        )

        print(
            traceback.format_exc()
        )

        return jsonify({
            "error": "Grading failed unexpectedly"
        }), 500

    finally:

        conn.close()