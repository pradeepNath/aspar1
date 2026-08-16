"""
routes/roadmap.py
"""

import json
from flask import Blueprint, request, jsonify, g

from config.db import get_db_connection
from utils.auth import token_required
from services.groq_service import generate_roadmap

roadmap_bp = Blueprint("roadmap", __name__)


def _make_serializable(obj):
    """Convert PostgreSQL types to JSON-serializable Python types."""
    from decimal import Decimal
    if isinstance(obj, list):
        return [_make_serializable(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    # Convert memoryview (psycopg2 returns this for some binary types)
    if isinstance(obj, memoryview):
        return obj.tobytes().decode("utf-8")
    return obj


@roadmap_bp.route("/roadmap/generate", methods=["POST"])
@token_required
def create_roadmap():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

            cursor.execute(
                "SELECT dream_career FROM student_profiles WHERE user_id = %s",
                (g.user_id,)
            )
            profile = cursor.fetchone()
            if not profile:
                return jsonify({"error": "Dream career not set"}), 422

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
            if not level_row:
                return jsonify({"error": "Placement not completed yet"}), 422

            current_level = level_row["current_level"]

            cursor.execute(
                """
                SELECT level, category, skill_name, sequence_order, status
                FROM skill_tree
                WHERE user_id = %s AND career = %s AND level <= %s
                ORDER BY level ASC, sequence_order ASC
                """,
                (g.user_id, dream, current_level)
            )
            skill_tree = cursor.fetchall()

            cursor.execute(
                """
                SELECT qs.test_type, qs.level,
                       ROUND(CAST(SUM(qsc.score_out_of_10) AS NUMERIC) /
                             (COUNT(qsc.id) * 10.0) * 100, 1) AS total_score_percent
                FROM quiz_sessions qs
                JOIN quiz_scores qsc ON qsc.session_id = qs.id
                WHERE qs.user_id = %s
                GROUP BY qs.id, qs.test_type, qs.level
                ORDER BY qs.created_at DESC
                LIMIT 5
                """,
                (g.user_id,)
            )
            scores = cursor.fetchall()

            cursor.execute(
                """
                SELECT notes FROM progress_log
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (g.user_id,)
            )
            log_row = cursor.fetchone()
            gaps = []
            if log_row and log_row.get("notes"):
                raw_notes = log_row["notes"]
                if raw_notes.startswith("gaps:"):
                    gaps = [g2.strip() for g2 in raw_notes[5:].split(",") if g2.strip()]

            cursor.execute(
                "SELECT MAX(version) AS max_v FROM roadmaps WHERE user_id = %s",
                (g.user_id,)
            )
            ver_row      = cursor.fetchone()
            next_version = (ver_row["max_v"] or 0) + 1

        # Serialize everything before passing to AI
        skill_tree_clean = _make_serializable(list(skill_tree))
        scores_clean     = _make_serializable(list(scores))
        academics_clean  = _make_serializable(list(academics))

        try:
            result = generate_roadmap(dream, academics_clean, skill_tree_clean, scores_clean, gaps)
        except Exception as e:
            print(f"[roadmap/generate] AI error: {e}")
            import traceback; print(traceback.format_exc())
            return jsonify({"error": "AI failed to generate roadmap. Please try again."}), 500

        overview      = result.get("overview", "")
        current_skill = result.get("current_skill")

        if not overview:
            return jsonify({"error": "AI returned an empty roadmap. Please try again."}), 500

        stored_payload = json.dumps({
            "overview":      overview,
            "current_skill": current_skill,
        })

        conn2 = get_db_connection()
        try:
            with conn2.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO roadmaps (user_id, roadmap_text, version)
                    VALUES (%s, %s, %s)
                    """,
                    (g.user_id, stored_payload, next_version)
                )
        finally:
            conn2.close()

        response = {
            "version":  next_version,
            "overview": overview,
        }
        if current_skill:
            response["current_skill"] = current_skill

        return jsonify(response), 201

    except Exception as e:
        print(f"[roadmap/generate] error: {e}")
        import traceback; print(traceback.format_exc())
        return jsonify({"error": "Could not generate roadmap"}), 500

    finally:
        conn.close()


@roadmap_bp.route("/roadmap", methods=["GET"])
@token_required
def get_roadmap():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT version, roadmap_text, created_at
                FROM roadmaps
                WHERE user_id = %s
                ORDER BY version DESC
                LIMIT 1
                """,
                (g.user_id,)
            )
            row = cursor.fetchone()

        if not row:
            return jsonify({"error": "No roadmap found. Generate one first."}), 404

        try:
            payload       = json.loads(row["roadmap_text"])
            overview      = payload.get("overview", "")
            current_skill = payload.get("current_skill")
        except (TypeError, ValueError):
            overview      = row["roadmap_text"]
            current_skill = None

        response = {
            "version":  row["version"],
            "overview": overview,
        }
        if current_skill:
            response["current_skill"] = current_skill
        if row.get("created_at"):
            response["created_at"] = row["created_at"].isoformat()

        return jsonify(response), 200

    except Exception as e:
        print(f"[roadmap/get] error: {e}")
        return jsonify({"error": "Could not fetch roadmap"}), 500

    finally:
        conn.close()