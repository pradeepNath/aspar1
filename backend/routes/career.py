"""
routes/career.py
"""

import json
from decimal import Decimal
from flask import Blueprint, request, jsonify, g

from config.db import get_db_connection
from utils.auth import token_required
from services.groq_service import suggest_alternative_careers

career_bp = Blueprint("career", __name__)

FAILURE_STREAK_THRESHOLD = 3


def _make_serializable(obj):
    if isinstance(obj, list):
        return [_make_serializable(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


@career_bp.route("/career/suggest", methods=["POST"])
@token_required
def suggest_careers():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

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
                gaps = [item.strip() for item in gap_row["notes"][5:].split(",") if item.strip()]

        performance_data = _make_serializable({
            "dream_career":         dream,
            "current_level":        current_level,
            "academics":            academics,
            "score_history":        score_history,
            "knowledge_gaps":       gaps,
            "consecutive_failures": consecutive_failures,
        })

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


@career_bp.route("/career/switch", methods=["POST"])
@token_required
def switch_career():
    data       = request.get_json(silent=True) or {}
    new_career = (data.get("new_career") or "").strip()

    if not new_career:
        return jsonify({"error": "new_career is required"}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

            cursor.execute(
                "UPDATE student_profiles SET dream_career = %s WHERE user_id = %s",
                (new_career, g.user_id)
            )

            cursor.execute(
                """
                INSERT INTO skill_levels (user_id, career, current_level)
                VALUES (%s, %s, 1)
                ON CONFLICT (user_id, career) DO UPDATE SET current_level = 1
                """,
                (g.user_id, new_career)
            )

        return jsonify({
            "message":    f"Career switched to {new_career}",
            "new_career":  new_career,
            "next_step":  "Take your placement test for the new career.",
        }), 200

    except Exception as e:
        print(f"[career/switch] error: {e}")
        return jsonify({"error": "Could not switch career"}), 500

    finally:
        conn.close()