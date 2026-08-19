"""
services/gap_analysis.py
-------------------------
Pure logic — no AI calls.

Analyzes skill test results to identify:
  - Which concepts the student is strong/weak in
  - Which weak concepts are persistent across attempts
  - Score trend vs previous attempts
  - Whether the weakness blocks the next skill
  - Skill type from the skill_tree record

Called from grading.py after every skill_test is graded.

The output of this analysis is what the roadmap AI receives
as structured input — making the roadmap equitable because
it responds to THIS student's actual evidence, not a generic template.
"""

import json


# ================================================================
# SCORE THRESHOLDS
# ================================================================

STRONG_THRESHOLD = 70    # >= 70% = strong concept
WEAK_THRESHOLD = 50      # < 50% = weak concept
BLOCK_THRESHOLD = 60     # overall < 60% = blocks next skill


# ================================================================
# CONCEPT NORMALIZATION
# ================================================================

def normalize_concept(value):
    """
    Normalize concept names so small formatting differences
    don't prevent matching.

    Example:

        "Repository Initialization"
        " repository initialization "
        "REPOSITORY INITIALIZATION"

    all become:

        "repository initialization"
    """

    if not value:
        return ""

    return " ".join(
        str(value)
        .strip()
        .lower()
        .split()
    )


# ================================================================
# EXTRACT CONCEPTS FROM STORED JSON
# ================================================================

def extract_weak_concepts_from_row(row):
    """
    Extract concept names from the weak_concepts JSON stored
    in skill_gap_analysis.

    Supports both:

        [{"concept": "...", "score": 20}]

    and:

        ["Repository Initialization"]
    """

    concepts = []

    try:

        weak_concepts = json.loads(
            row["weak_concepts"] or "[]"
        )

        if not isinstance(weak_concepts, list):
            return concepts

        for item in weak_concepts:

            if isinstance(item, dict):

                concept = item.get("concept")

            else:

                concept = item

            normalized = normalize_concept(
                concept
            )

            if normalized:

                concepts.append(normalized)

    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        pass

    return concepts


# ================================================================
# ANALYZE SKILL GAPS
# ================================================================

def analyze_skill_gaps(
    conn,
    user_id,
    skill_id,
    session_id,
    questions_rows,
    ai_results_map,
    overall_score,
):
    """
    Analyze skill test results.

    IMPORTANT:

    This function is the ONLY place responsible for deciding
    whether a weak concept is persistent.

    Definitions:

      weak_concepts
          = concepts weak in THIS attempt.

      persistent_weak_concepts
          = concepts weak in THIS attempt AND weak in at least
            one PREVIOUS attempt of the SAME core skill.

    Personalized subskills should ONLY be generated from
    persistent_weak_concepts.
    """

    with conn.cursor() as cursor:

        # =========================================================
        # 1. GET CORE SKILL INFORMATION
        # =========================================================

        cursor.execute(
            """
            SELECT
                skill_name,
                skill_type,
                sequence_order,
                level,
                career
            FROM skill_tree
            WHERE id = %s
              AND user_id = %s
            """,
            (
                skill_id,
                user_id,
            ),
        )

        skill = cursor.fetchone()

        if not skill:

            return None

        skill_type = (
            skill["skill_type"]
            or "mixed"
        )

        sequence_order = skill["sequence_order"]
        level = skill["level"]
        career = skill["career"]

        # =========================================================
        # 2. AGGREGATE CURRENT TEST SCORES BY CONCEPT
        # =========================================================

        concept_scores = {}

        for question in questions_rows:

            concept = (
                question.get("concept")
                or "General"
            ).strip()

            ai_result = ai_results_map.get(
                question["question_number"],
                {},
            )

            score = float(
                ai_result.get(
                    "score_out_of_10",
                    0,
                )
            ) * 10

            if concept not in concept_scores:

                concept_scores[concept] = []

            concept_scores[concept].append(
                score
            )

        # =========================================================
        # 3. CALCULATE CONCEPT AVERAGES
        # =========================================================

        concept_averages = {
            concept: round(
                sum(scores) / len(scores),
                1,
            )
            for concept, scores
            in concept_scores.items()
        }

        # =========================================================
        # 4. CURRENT STRONG CONCEPTS
        # =========================================================

        strong_concepts = [
            {
                "concept": concept,
                "score": score,
            }
            for concept, score
            in concept_averages.items()
            if score >= STRONG_THRESHOLD
        ]

        # =========================================================
        # 5. CURRENT WEAK CONCEPTS
        # =========================================================

        weak_concepts = [
            {
                "concept": concept,
                "score": score,
            }
            for concept, score
            in concept_averages.items()
            if score < WEAK_THRESHOLD
        ]

        weak_concepts.sort(
            key=lambda item: item["score"]
        )

        strong_concepts.sort(
            key=lambda item: item["score"],
            reverse=True,
        )

        # =========================================================
        # 6. FIND PREVIOUS ATTEMPTS
        # =========================================================
        #
        # IMPORTANT:
        #
        # We exclude the current session.
        #
        # We only look at attempts for THIS SAME skill.
        #
        # Example:
        #
        # Attempt 1:
        #   Repository Initialization = 0%
        #
        # Attempt 2:
        #   Repository Initialization = 20%
        #
        # Then on Attempt 2:
        #
        #   persistent_weak_concepts =
        #       Repository Initialization
        #
        # =========================================================

        cursor.execute(
            """
            SELECT
                session_id,
                weak_concepts,
                overall_score,
                attempt_number,
                analyzed_at
            FROM skill_gap_analysis
            WHERE user_id = %s
              AND skill_id = %s
              AND session_id <> %s
            ORDER BY analyzed_at DESC
            LIMIT 10
            """,
            (
                user_id,
                skill_id,
                session_id,
            ),
        )

        previous_rows = cursor.fetchall()

        # =========================================================
        # 7. BUILD SET OF PREVIOUSLY WEAK CONCEPTS
        # =========================================================

        previous_weak_concepts = set()

        for row in previous_rows:

            old_concepts = (
                extract_weak_concepts_from_row(
                    row
                )
            )

            for concept in old_concepts:

                previous_weak_concepts.add(
                    concept
                )

        # =========================================================
        # 8. DETERMINE PERSISTENT GAPS
        # =========================================================
        #
        # A concept becomes persistent ONLY when:
        #
        #   CURRENT attempt:
        #       score < 50%
        #
        # AND
        #
        #   PREVIOUS attempt:
        #       same concept was weak
        #
        # This means one failure alone can NEVER generate
        # a personalized subskill.
        # =========================================================

        persistent_weak_concepts = []

        for item in weak_concepts:

            concept = item["concept"]

            normalized = normalize_concept(
                concept
            )

            if (
                normalized
                in previous_weak_concepts
            ):

                persistent_weak_concepts.append(
                    {
                        "concept": concept,
                        "score": item["score"],
                    }
                )

        # =========================================================
        # 9. SCORE TREND / ATTEMPT NUMBER
        # =========================================================

        cursor.execute(
            """
            SELECT
                overall_score,
                attempt_number
            FROM skill_gap_analysis
            WHERE user_id = %s
              AND skill_id = %s
              AND session_id <> %s
            ORDER BY analyzed_at DESC
            LIMIT 1
            """,
            (
                user_id,
                skill_id,
                session_id,
            ),
        )

        previous_attempt = cursor.fetchone()

        if previous_attempt is None:

            score_trend = "first_attempt"
            score_delta = 0.0
            attempt_number = 1

        else:

            previous_score = float(
                previous_attempt[
                    "overall_score"
                ]
                or 0
            )

            attempt_number = (
                int(
                    previous_attempt[
                        "attempt_number"
                    ]
                    or 0
                )
                + 1
            )

            score_delta = round(
                float(overall_score)
                - previous_score,
                1,
            )

            if score_delta >= 5:

                score_trend = "improving"

            elif score_delta <= -5:

                score_trend = "declining"

            else:

                score_trend = "stable"

        # =========================================================
        # 10. DETERMINE WHETHER CURRENT SKILL BLOCKS NEXT SKILL
        # =========================================================

        blocks_next = False

        if float(overall_score) < BLOCK_THRESHOLD:

            cursor.execute(
                """
                SELECT id
                FROM skill_tree
                WHERE user_id = %s
                  AND career = %s
                  AND level = %s
                  AND sequence_order > %s
                ORDER BY sequence_order ASC
                LIMIT 1
                """,
                (
                    user_id,
                    career,
                    level,
                    sequence_order,
                ),
            )

            next_skill = cursor.fetchone()

            if next_skill:

                blocks_next = True

        # =========================================================
        # 11. SAVE CURRENT ANALYSIS
        # =========================================================
        #
        # We store the CURRENT weak concepts.
        #
        # We do NOT need a separate persistent_weak_concepts
        # database column because persistence can be determined
        # by comparing the current attempt with previous records.
        #
        # This keeps the database schema unchanged.
        # =========================================================

        cursor.execute(
            """
            INSERT INTO skill_gap_analysis
                (
                    user_id,
                    skill_id,
                    session_id,
                    skill_type,
                    overall_score,
                    weak_concepts,
                    strong_concepts,
                    score_trend,
                    score_delta,
                    attempt_number,
                    blocks_next
                )
            VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
            ON CONFLICT
                (
                    user_id,
                    skill_id,
                    session_id
                )
            DO UPDATE SET
                overall_score =
                    EXCLUDED.overall_score,

                weak_concepts =
                    EXCLUDED.weak_concepts,

                strong_concepts =
                    EXCLUDED.strong_concepts,

                score_trend =
                    EXCLUDED.score_trend,

                score_delta =
                    EXCLUDED.score_delta,

                attempt_number =
                    EXCLUDED.attempt_number,

                blocks_next =
                    EXCLUDED.blocks_next,

                analyzed_at =
                    NOW()
            """,
            (
                user_id,
                skill_id,
                session_id,
                skill_type,
                overall_score,
                json.dumps(
                    weak_concepts
                ),
                json.dumps(
                    strong_concepts
                ),
                score_trend,
                score_delta,
                attempt_number,
                blocks_next,
            ),
        )

        # =========================================================
        # 12. RETURN COMPLETE ANALYSIS
        # =========================================================

        return {
            "skill_name": skill["skill_name"],
            "skill_type": skill_type,
            "overall_score": overall_score,

            # Weak in THIS attempt.
            "weak_concepts": weak_concepts,

            # Strong in THIS attempt.
            "strong_concepts": strong_concepts,

            # Weak in THIS attempt AND a previous attempt.
            "persistent_weak_concepts": (
                persistent_weak_concepts
            ),

            "score_trend": score_trend,
            "score_delta": score_delta,
            "attempt_number": attempt_number,
            "blocks_next": blocks_next,
        }


# ================================================================
# LEARNER MODEL
# ================================================================

def get_learner_model(conn, user_id):
    """
    Build a snapshot of the learner's current state from existing
    tables.

    No AI — pure SQL aggregation.

    Returns a dict that can be passed to generate_roadmap() or
    explain_readiness() to make AI responses personalized.

    Structure:

    {
      "current_level": 2,
      "dream_career": "Data Scientist",
      "skill_mastery": [
        {
            "skill_name": "Python",
            "score": 89.0,
            "trend": "improving"
        }
      ],
      "strong_skills": ["Python"],
      "weak_skills": ["Statistics"],
      "persistent_gaps": [
          "Bayes Theorem"
      ],
      "academic_trend": "improving",
      "overall_trend": "improving",
      "total_attempts": 8,
      "pass_rate": 62.5
    }
    """

    with conn.cursor() as cursor:

        # =========================================================
        # BASIC PROFILE
        # =========================================================

        cursor.execute(
            """
            SELECT
                sp.dream_career,
                sl.current_level
            FROM student_profiles sp
            JOIN skill_levels sl
                ON sl.user_id = sp.user_id
               AND sl.career = sp.dream_career
            WHERE sp.user_id = %s
            """,
            (user_id,),
        )

        profile = cursor.fetchone()

        if not profile:

            return {}

        dream = profile["dream_career"]

        current_level = profile[
            "current_level"
        ]

        # =========================================================
        # PER-SKILL MASTERY
        # =========================================================

        cursor.execute(
            """
            SELECT DISTINCT ON (sga.skill_id)
                st.skill_name,
                st.skill_type,
                sga.overall_score,
                sga.score_trend,
                sga.score_delta,
                sga.weak_concepts,
                sga.strong_concepts,
                sga.attempt_number
            FROM skill_gap_analysis sga
            JOIN skill_tree st
                ON st.id = sga.skill_id
            WHERE sga.user_id = %s
            ORDER BY
                sga.skill_id,
                sga.analyzed_at DESC
            """,
            (user_id,),
        )

        skill_rows = cursor.fetchall()

        skill_mastery = []
        strong_skills = []
        weak_skills = []

        for row in skill_rows:

            score = float(
                row["overall_score"]
                or 0
            )

            skill_mastery.append(
                {
                    "skill_name":
                        row["skill_name"],

                    "skill_type":
                        row["skill_type"],

                    "score":
                        score,

                    "trend":
                        row["score_trend"],

                    "attempts":
                        row["attempt_number"],
                }
            )

            if score >= 80:

                strong_skills.append(
                    row["skill_name"]
                )

            elif score < 60:

                weak_skills.append(
                    row["skill_name"]
                )

        # =========================================================
        # PERSISTENT CONCEPT GAPS
        # =========================================================
        #
        # Do NOT assume:
        #
        #   attempt_number >= 2
        #   AND latest score < 60
        #
        # means every latest weak concept is persistent.
        #
        # Instead, compare the actual concepts across attempts.
        # =========================================================

        cursor.execute(
            """
            SELECT
                skill_id,
                session_id,
                weak_concepts,
                analyzed_at
            FROM skill_gap_analysis
            WHERE user_id = %s
            ORDER BY analyzed_at ASC
            """,
            (user_id,),
        )

        all_gap_rows = cursor.fetchall()

        concept_attempts = {}

        for row in all_gap_rows:

            skill_key = row["skill_id"]

            concepts = (
                extract_weak_concepts_from_row(
                    row
                )
            )

            if skill_key not in concept_attempts:

                concept_attempts[
                    skill_key
                ] = {}

            for concept in concepts:

                if concept not in concept_attempts[
                    skill_key
                ]:

                    concept_attempts[
                        skill_key
                    ][concept] = 0

                concept_attempts[
                    skill_key
                ][concept] += 1

        persistent_gaps = []

        for skill_concepts in (
            concept_attempts.values()
        ):

            for concept, count in (
                skill_concepts.items()
            ):

                if count >= 2:

                    persistent_gaps.append(
                        concept
                    )

        # =========================================================
        # OVERALL LEARNING TREND
        # =========================================================

        improving_count = sum(
            1
            for s in skill_mastery
            if s["trend"] == "improving"
        )

        declining_count = sum(
            1
            for s in skill_mastery
            if s["trend"] == "declining"
        )

        if (
            improving_count
            > declining_count
        ):

            overall_trend = "improving"

        elif (
            declining_count
            > improving_count
        ):

            overall_trend = "declining"

        else:

            overall_trend = "stable"

        # =========================================================
        # ACADEMIC TREND
        # =========================================================

        cursor.execute(
            """
            SELECT
                gpa,
                uploaded_at
            FROM academic_results
            WHERE user_id = %s
              AND gpa IS NOT NULL
            ORDER BY uploaded_at ASC
            """,
            (user_id,),
        )

        academic_rows = (
            cursor.fetchall()
        )

        academic_trend = (
            "insufficient_data"
        )

        if len(academic_rows) >= 2:

            gpas = [
                float(row["gpa"])
                for row in academic_rows
            ]

            midpoint = len(gpas) // 2

            first_half = gpas[:midpoint]
            second_half = gpas[midpoint:]

            if first_half and second_half:

                avg_first_half = (
                    sum(first_half)
                    / len(first_half)
                )

                avg_second_half = (
                    sum(second_half)
                    / len(second_half)
                )

                difference = (
                    avg_second_half
                    - avg_first_half
                )

                if difference >= 0.2:

                    academic_trend = (
                        "improving"
                    )

                elif difference <= -0.2:

                    academic_trend = (
                        "declining"
                    )

                else:

                    academic_trend = (
                        "stable"
                    )

        # =========================================================
        # PASS RATE
        # =========================================================

        cursor.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(
                    CASE
                        WHEN session_avg >= 80
                        THEN 1
                        ELSE 0
                    END
                ) AS passed
            FROM
            (
                SELECT
                    sess.id,

                    ROUND(
                        CAST(
                            SUM(
                                qs.score_out_of_10
                            )
                            AS NUMERIC
                        )
                        /
                        (
                            COUNT(qs.id)
                            * 10.0
                        )
                        * 100,
                        1
                    ) AS session_avg

                FROM quiz_sessions sess

                JOIN quiz_scores qs
                    ON qs.session_id =
                       sess.id

                WHERE sess.user_id = %s

                GROUP BY sess.id
            ) sub
            """,
            (user_id,),
        )

        perf = cursor.fetchone()

        total_attempts = (
            int(perf["total"] or 0)
            if perf
            else 0
        )

        passed = (
            int(perf["passed"] or 0)
            if perf
            else 0
        )

        pass_rate = (
            round(
                (passed / total_attempts)
                * 100,
                1,
            )
            if total_attempts > 0
            else 0.0
        )

        # =========================================================
        # PASSION STATEMENT
        # =========================================================

        cursor.execute(
            """
            SELECT passion_statement
            FROM student_profiles
            WHERE user_id = %s
            """,
            (user_id,),
        )

        prof_row = cursor.fetchone()

        passion_statement = (
            prof_row["passion_statement"]
            if prof_row
            else ""
        )

        # =========================================================
        # RETURN LEARNER MODEL
        # =========================================================

        return {
            "dream_career": dream,

            "current_level":
                current_level,

            "passion_statement":
                passion_statement,

            "skill_mastery":
                skill_mastery,

            "strong_skills":
                strong_skills,

            "weak_skills":
                weak_skills,

            "persistent_gaps":
                sorted(
                    set(
                        persistent_gaps
                    )
                ),

            "academic_trend":
                academic_trend,

            "overall_trend":
                overall_trend,

            "total_attempts":
                total_attempts,

            "pass_rate":
                pass_rate,
        }