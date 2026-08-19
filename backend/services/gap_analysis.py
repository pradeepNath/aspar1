"""
services/gap_analysis.py
-------------------------
Pure logic — no AI calls.

Analyzes skill test results to identify:
  - Which concepts the student is strong/weak in
  - Score trend vs previous attempts
  - Whether the weakness blocks the next skill
  - Skill type from the skill_tree record

Called from grading.py after every skill_test is graded.
Results saved to skill_gap_analysis table.

The output of this analysis is what the roadmap AI receives
as structured input — making the roadmap equitable because
it responds to THIS student's actual evidence, not a generic template.
"""

import json
from datetime import datetime, timezone


# Score thresholds
STRONG_THRESHOLD = 70    # >= 70% on a question = strong concept
WEAK_THRESHOLD   = 50    # <  50% on a question = weak concept
BLOCK_THRESHOLD  = 60    # overall < 60% = blocks next skill


def analyze_skill_gaps(conn, user_id, skill_id, session_id, questions_rows,
                        ai_results_map, overall_score):
    """
    Analyze skill test results to extract structured gap data.
    Save the result to skill_gap_analysis.

    Args:
        conn:            active DB connection
        user_id:         int
        skill_id:        int — the skill_tree.id being tested
        session_id:      int — quiz_sessions.id
        questions_rows:  list of question dicts from quiz_questions
                         (must include 'concept' field)
        ai_results_map:  dict of question_number -> grading result
                         (score_out_of_10, feedback)
        overall_score:   float — total_score_percent for this session

    Returns:
        dict — the gap analysis record that was saved
    """
    with conn.cursor() as cursor:

        # --- Fetch skill info ---
        cursor.execute(
            """
            SELECT skill_name, skill_type, sequence_order, level, career
            FROM skill_tree WHERE id = %s AND user_id = %s
            """,
            (skill_id, user_id)
        )
        skill = cursor.fetchone()
        if not skill:
            return None

        skill_type     = skill["skill_type"] or "mixed"
        sequence_order = skill["sequence_order"]
        level          = skill["level"]
        career         = skill["career"]

        # --- Aggregate scores by concept ---
        concept_scores = {}   # concept -> [scores]
        for q in questions_rows:
            concept = q.get("concept") or "General"
            ai_r    = ai_results_map.get(q["question_number"], {})
            score   = float(ai_r.get("score_out_of_10", 0)) * 10  # convert to %

            if concept not in concept_scores:
                concept_scores[concept] = []
            concept_scores[concept].append(score)

        # Average score per concept
        concept_averages = {
            concept: round(sum(scores) / len(scores), 1)
            for concept, scores in concept_scores.items()
        }

        # Classify concepts as strong or weak
        strong_concepts = [
            {"concept": c, "score": s}
            for c, s in concept_averages.items()
            if s >= STRONG_THRESHOLD
        ]
        weak_concepts = [
            {"concept": c, "score": s}
            for c, s in concept_averages.items()
            if s < WEAK_THRESHOLD
        ]

        # Sort weak concepts by score (worst first)
        weak_concepts.sort(key=lambda x: x["score"])
        strong_concepts.sort(key=lambda x: x["score"], reverse=True)

        # --- Score trend vs previous attempt on this same skill ---
        cursor.execute(
            """
            SELECT sga.overall_score, sga.attempt_number
            FROM skill_gap_analysis sga
            WHERE sga.user_id = %s AND sga.skill_id = %s
            ORDER BY sga.analyzed_at DESC
            LIMIT 1
            """,
            (user_id, skill_id)
        )
        prev = cursor.fetchone()

        if prev is None:
            score_trend    = "first_attempt"
            score_delta    = 0.0
            attempt_number = 1
        else:
            prev_score     = float(prev["overall_score"])
            attempt_number = int(prev["attempt_number"]) + 1
            score_delta    = round(overall_score - prev_score, 1)

            if score_delta >= 5:
                score_trend = "improving"
            elif score_delta <= -5:
                score_trend = "declining"
            else:
                score_trend = "stable"

        # --- Does this weakness block the next skill? ---
        # Check if there is a next skill in sequence at the same level
        blocks_next = False
        if overall_score < BLOCK_THRESHOLD:
            cursor.execute(
                """
                SELECT id FROM skill_tree
                WHERE user_id = %s AND career = %s AND level = %s
                  AND sequence_order > %s
                ORDER BY sequence_order ASC
                LIMIT 1
                """,
                (user_id, career, level, sequence_order)
            )
            next_skill = cursor.fetchone()
            if next_skill:
                blocks_next = True

        # --- Save to skill_gap_analysis ---
        # Use ON CONFLICT to update if this session was already analyzed
        cursor.execute(
            """
            INSERT INTO skill_gap_analysis
                (user_id, skill_id, session_id, skill_type, overall_score,
                 weak_concepts, strong_concepts, score_trend, score_delta,
                 attempt_number, blocks_next)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, skill_id, session_id) DO UPDATE SET
                overall_score   = EXCLUDED.overall_score,
                weak_concepts   = EXCLUDED.weak_concepts,
                strong_concepts = EXCLUDED.strong_concepts,
                score_trend     = EXCLUDED.score_trend,
                score_delta     = EXCLUDED.score_delta,
                attempt_number  = EXCLUDED.attempt_number,
                blocks_next     = EXCLUDED.blocks_next,
                analyzed_at     = NOW()
            """,
            (
                user_id,
                skill_id,
                session_id,
                skill_type,
                overall_score,
                json.dumps(weak_concepts),
                json.dumps(strong_concepts),
                score_trend,
                score_delta,
                attempt_number,
                blocks_next,
            )
        )

        return {
            "skill_name":       skill["skill_name"],
            "skill_type":       skill_type,
            "overall_score":    overall_score,
            "weak_concepts":    weak_concepts,
            "strong_concepts":  strong_concepts,
            "score_trend":      score_trend,
            "score_delta":      score_delta,
            "attempt_number":   attempt_number,
            "blocks_next":      blocks_next,
        }


def get_learner_model(conn, user_id):
    """
    Build a snapshot of the learner's current state from existing tables.
    No AI — pure SQL aggregation.

    Returns a dict that can be passed to generate_roadmap() or
    explain_readiness() to make AI responses personalized.

    Structure:
    {
      "current_level": 2,
      "dream_career": "Data Scientist",
      "skill_mastery": [
        {"skill_name": "Python", "score": 89.0, "trend": "improving"},
        {"skill_name": "Statistics", "score": 43.0, "trend": "stable"},
      ],
      "strong_skills": ["Python", "Data Visualization"],
      "weak_skills": ["Statistics", "Linear Algebra"],
      "persistent_gaps": ["Bayes Theorem", "Hypothesis Testing"],
      "academic_trend": "improving",
      "overall_trend": "improving",
      "total_attempts": 8,
      "pass_rate": 62.5
    }
    """
    with conn.cursor() as cursor:

        # Basic profile
        cursor.execute(
            """
            SELECT sp.dream_career, sl.current_level
            FROM student_profiles sp
            JOIN skill_levels sl ON sl.user_id = sp.user_id
                                 AND sl.career = sp.dream_career
            WHERE sp.user_id = %s
            """,
            (user_id,)
        )
        profile = cursor.fetchone()
        if not profile:
            return {}

        dream         = profile["dream_career"]
        current_level = profile["current_level"]

        # Per-skill mastery from gap analysis (latest per skill)
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
            JOIN skill_tree st ON st.id = sga.skill_id
            WHERE sga.user_id = %s
            ORDER BY sga.skill_id, sga.analyzed_at DESC
            """,
            (user_id,)
        )
        skill_rows = cursor.fetchall()

        skill_mastery = []
        strong_skills = []
        weak_skills   = []
        persistent_gaps = []

        for row in skill_rows:
            score = float(row["overall_score"] or 0)
            skill_mastery.append({
                "skill_name": row["skill_name"],
                "skill_type": row["skill_type"],
                "score":      score,
                "trend":      row["score_trend"],
                "attempts":   row["attempt_number"],
            })

            if score >= 80:
                strong_skills.append(row["skill_name"])
            elif score < 60:
                weak_skills.append(row["skill_name"])

            # Persistent gap = attempted 2+ times, still below 60%
            if int(row["attempt_number"] or 1) >= 2 and score < 60:
                try:
                    weak_c = json.loads(row["weak_concepts"] or "[]")
                    persistent_gaps.extend([c["concept"] for c in weak_c])
                except Exception:
                    pass

        # Overall learning trend — are scores going up?
        improving_count = sum(
            1 for s in skill_mastery if s["trend"] == "improving"
        )
        declining_count = sum(
            1 for s in skill_mastery if s["trend"] == "declining"
        )
        if improving_count > declining_count:
            overall_trend = "improving"
        elif declining_count > improving_count:
            overall_trend = "declining"
        else:
            overall_trend = "stable"

        # Academic trend
        cursor.execute(
            """
            SELECT gpa, uploaded_at FROM academic_results
            WHERE user_id = %s AND gpa IS NOT NULL
            ORDER BY uploaded_at ASC
            """,
            (user_id,)
        )
        academic_rows = cursor.fetchall()

        academic_trend = "insufficient_data"
        if len(academic_rows) >= 2:
            gpas = [float(r["gpa"]) for r in academic_rows]
            avg_first_half  = sum(gpas[:len(gpas)//2]) / (len(gpas)//2)
            avg_second_half = sum(gpas[len(gpas)//2:]) / (len(gpas) - len(gpas)//2)
            if avg_second_half - avg_first_half >= 0.2:
                academic_trend = "improving"
            elif avg_first_half - avg_second_half >= 0.2:
                academic_trend = "declining"
            else:
                academic_trend = "stable"

        # Pass rate across all sessions
        cursor.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN session_avg >= 80 THEN 1 ELSE 0 END) AS passed
            FROM (
                SELECT sess.id,
                       ROUND(CAST(SUM(qs.score_out_of_10) AS NUMERIC) /
                             (COUNT(qs.id) * 10.0) * 100, 1) AS session_avg
                FROM quiz_sessions sess
                JOIN quiz_scores qs ON qs.session_id = sess.id
                WHERE sess.user_id = %s
                GROUP BY sess.id
            ) sub
            """,
            (user_id,)
        )
        perf = cursor.fetchone()
        total_attempts = int(perf["total"] or 0) if perf else 0
        passed         = int(perf["passed"] or 0) if perf else 0
        pass_rate      = round((passed / total_attempts) * 100, 1) if total_attempts > 0 else 0.0

        # Passion statement
        cursor.execute(
            "SELECT passion_statement FROM student_profiles WHERE user_id = %s",
            (user_id,)
        )
        prof_row          = cursor.fetchone()
        passion_statement = prof_row["passion_statement"] if prof_row else ""

        return {
            "dream_career":     dream,
            "current_level":    current_level,
            "passion_statement": passion_statement,
            "skill_mastery":    skill_mastery,
            "strong_skills":    strong_skills,
            "weak_skills":      weak_skills,
            "persistent_gaps":  list(set(persistent_gaps)),
            "academic_trend":   academic_trend,
            "overall_trend":    overall_trend,
            "total_attempts":   total_attempts,
            "pass_rate":        pass_rate,
        }