"""
routes/career.py
-----------------
Handles the career-change flow (Section 4, step 10):

    POST /api/career/suggest
        - Only callable when the student has 3+ consecutive failed
          level-up attempts (score < 80%), enforced in code, not AI
        - Calls suggest_alternative_careers() (AI function 8)
        - Returns 3 alternative career suggestions

    POST /api/career/switch
        - Student accepts a new career path
        - Resets skill_levels for the new career
        - Student goes through placement test fresh for the new career

IMPORTANT (Section 4 & 10):
    Career change is ALWAYS opt-in. The frontend asks the student
    "Would you like to explore careers matching your strengths?" and only
    calls /api/career/suggest if the student says Yes. /api/career/switch
    is only called if the student explicitly chooses one of the 3 options.
"""

import json
from decimal import Decimal
from flask import Blueprint, request, jsonify, g

from config.db import get_db_connection
from utils.auth import token_required
from services.groq_service import suggest_alternative_careers

career_bp = Blueprint("career", __name__)

# How many consecutive failed (<80%) level-up attempts before career
# suggestions become available. Must match the same constant in progress.py.
FAILURE_STREAK_THRESHOLD = 3


def _make_serializable(obj):
    """
    Recursively convert a DB result (list/dict) into something json.dumps()
    can handle. PyMySQL returns ROUND() results as Decimal — json.dumps
    raises TypeError on those, which surfaces as a generic 500 before the
    AI call even happens.
    """
    if isinstance(obj, list):
        return [_make_serializable(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


# ============================================================
# POST /api/career/suggest
# ============================================================
@career_bp.route("/career/suggest", methods=["POST"])
@token_required
def suggest_careers():
    """
    Suggest 3 alternative careers based on actual performance data.

    No body required — context is pulled from the DB.

    Guard: returns 403 if the student has NOT yet had 3+ consecutive
    failed level-up attempts (score < 80%).

    On success (200):
        {
          "alternatives": [
            {"career": "UI/UX Designer", "reasoning": "..."},
            {"career": "Technical Writer", "reasoning": "..."},
            {"career": "QA Tester", "reasoning": "..."}
          ]
        }
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

            # --- Guard: verify the student qualifies ---
            # Uses a hard score-based streak, not the AI's 'eased' label.
            cursor.execute(
                """
                SELECT total_score FROM progress_log
                WHERE user_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT 10
                """,
                (g.user_id,)
            )
            recent_scores = [r["total_score"] for r in cursor.fetchall()]

            consecutive_failures = 0
            for score in recent_scores:
                if score is not None and float(score) < 80:
                    consecutive_failures += 1
                else:
                    break

            if consecutive_failures < FAILURE_STREAK_THRESHOLD:
                return jsonify({
                    "error": "Career suggestion is only available after repeated no-improvement results."
                }), 403

            # --- Gather performance context for the AI ---
            cursor.execute(
                "SELECT dream_career FROM student_profiles WHERE user_id = %s",
                (g.user_id,)
            )
            profile = cursor.fetchone()
            if not profile:
                return jsonify({"error": "Profile not found"}), 422
            dream = profile["dream_career"]

            cursor.execute(
                "SELECT current_level FROM skill_levels WHERE user_id = %s AND career = %s",
                (g.user_id, dream)
            )
            level_row     = cursor.fetchone()
            current_level = level_row["current_level"] if level_row else 1

            cursor.execute(
                "SELECT subject, grade, gpa FROM academic_results WHERE user_id = %s",
                (g.user_id,)
            )
            academics = cursor.fetchall()

            # Last 5 level-up test scores — may contain Decimal from ROUND()
            cursor.execute(
                """
                SELECT qs.test_type, qs.level,
                       ROUND(SUM(qsc.score_out_of_10) /
                             (COUNT(qsc.id) * 10.0) * 100, 1) AS total_score_percent
                FROM quiz_sessions qs
                JOIN quiz_scores qsc ON qsc.session_id = qs.id
                WHERE qs.user_id = %s AND qs.test_type = 'level_up'
                GROUP BY qs.id, qs.test_type, qs.level
                ORDER BY qs.created_at DESC
                LIMIT 5
                """,
                (g.user_id,)
            )
            score_history = cursor.fetchall()

            # Latest knowledge gaps from progress_log notes
            cursor.execute(
                """
                SELECT notes FROM progress_log
                WHERE user_id = %s AND notes LIKE 'gaps:%%'
                ORDER BY created_at DESC LIMIT 1
                """,
                (g.user_id,)
            )
            gap_row = cursor.fetchone()
            gaps    = []
            if gap_row and gap_row.get("notes"):
                raw = gap_row["notes"][5:]  # strip "gaps:" prefix
                gaps = [item.strip() for item in raw.split(",") if item.strip()]

        # Serialize everything — Decimal from ROUND() will break json.dumps
        # inside suggest_alternative_careers() without this step.
        performance_data = _make_serializable({
            "dream_career":   dream,
            "current_level":  current_level,
            "academics":      academics,
            "score_history":  score_history,
            "knowledge_gaps": gaps,
            "consecutive_failures": consecutive_failures,
        })

        # --- AI call (function 8) ---
        try:
            result = suggest_alternative_careers(performance_data)
        except Exception as e:
            print(f"[career/suggest] AI error: {e}")
            return jsonify({"error": "AI could not generate suggestions. Please try again."}), 500

        return jsonify(result), 200

    except Exception as e:
        import traceback
        print(f"[career/suggest] error: {e}")
        print(traceback.format_exc())
        return jsonify({"error": f"Could not generate career suggestions: {str(e)}"}), 500

    finally:
        conn.close()


# ============================================================
# POST /api/career/switch
# ============================================================
@career_bp.route("/career/switch", methods=["POST"])
@token_required
def switch_career():
    """
    Student accepts a new career path and starts fresh for it.

    Expected JSON body:
        { "new_career": "UI/UX Designer" }

    What this does:
        1. Updates student_profiles.dream_career to the new career
        2. Inserts a fresh skill_levels row for the new career
           (starting at level 1 — placement test will update it)
        3. Does NOT delete the old skill_tree or roadmaps — history
           is preserved so the student can review past progress.
        4. The student is now expected to go through:
              POST /api/quiz/start  (test_type: "placement")
              POST /api/quiz/submit
              POST /api/grading/run
              POST /api/skills/generate
              POST /api/roadmap/generate
           exactly as they did when first signing up.

    On success (200):
        {
          "message": "Career switched to UI/UX Designer",
          "new_career": "UI/UX Designer",
          "next_step": "Take your placement test for the new career."
        }
    """
    data       = request.get_json(silent=True) or {}
    new_career = (data.get("new_career") or "").strip()

    if not new_career:
        return jsonify({"error": "new_career is required"}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

            # Update dream career in profile
            cursor.execute(
                """
                UPDATE student_profiles SET dream_career = %s
                WHERE user_id = %s
                """,
                (new_career, g.user_id)
            )

            # Insert a fresh skill_levels row for the new career
            # (level 1 as placeholder; placement test will overwrite)
            cursor.execute(
                """
                INSERT INTO skill_levels (user_id, career, current_level)
                VALUES (%s, %s, 1)
                ON DUPLICATE KEY UPDATE current_level = 1
                """,
                (g.user_id, new_career)
            )

        return jsonify({
            "message":   f"Career switched to {new_career}",
            "new_career": new_career,
            "next_step": "Take your placement test for the new career.",
        }), 200

    except Exception as e:
        print(f"[career/switch] error: {e}")
        return jsonify({"error": "Could not switch career"}), 500

    finally:
        conn.close()