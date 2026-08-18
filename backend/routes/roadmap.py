"""
routes/roadmap.py
------------------
Rewired to use the learner model (services/gap_analysis.py) instead
of raw skill tree + basic scores. This is what makes the roadmap
equitable — the AI receives each student's actual demonstrated
strengths/weaknesses, not just their level and a generic skill list.

    POST /api/roadmap/generate
    GET  /api/roadmap
"""

import json
from flask import Blueprint, request, jsonify, g

from config.db import get_db_connection
from utils.auth import token_required
from services.groq_service import generate_roadmap
from services.gap_analysis import get_learner_model

roadmap_bp = Blueprint("roadmap", __name__)


@roadmap_bp.route("/roadmap/generate", methods=["POST"])
@token_required
def create_roadmap():
    """
    Generate (or regenerate) the student's roadmap using their full
    learner model as evidence — this is the equity engine in action.

    On success (201):
        {
          "version": 3,
          "overview": "...",
          "current_skill": {
            "skill_name": "...",
            "why_now": "...",
            "what_to_learn": "...",
            "resource_types": [...]
          }
        }
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

            # --- Profile + career ---
            cursor.execute(
                "SELECT dream_career FROM student_profiles WHERE user_id = %s",
                (g.user_id,)
            )
            profile = cursor.fetchone()
            if not profile:
                return jsonify({"error": "Dream career not set"}), 422
            dream = profile["dream_career"]

            # --- Current level ---
            cursor.execute(
                "SELECT current_level FROM skill_levels WHERE user_id = %s AND career = %s",
                (g.user_id, dream)
            )
            level_row = cursor.fetchone()
            if not level_row:
                return jsonify({"error": "Placement not completed yet"}), 422
            current_level = level_row["current_level"]

            # --- Find the current unlocked skill ---
            cursor.execute(
                """
                SELECT skill_name, skill_type, category
                FROM skill_tree
                WHERE user_id = %s AND career = %s AND level = %s
                  AND status = 'unlocked'
                ORDER BY sequence_order ASC
                LIMIT 1
                """,
                (g.user_id, dream, current_level)
            )
            current_skill_row = cursor.fetchone()
            current_skill = dict(current_skill_row) if current_skill_row else None

            # --- Next version number ---
            cursor.execute(
                "SELECT MAX(version) AS max_v FROM roadmaps WHERE user_id = %s",
                (g.user_id,)
            )
            ver_row      = cursor.fetchone()
            next_version = (ver_row["max_v"] or 0) + 1

        # --- Build the learner model (pure logic, no AI) ---
        learner_model = get_learner_model(conn, g.user_id)

        # --- AI call — receives learner model, writes personalized roadmap ---
        try:
            result = generate_roadmap(dream, current_skill, learner_model)
        except Exception as e:
            print(f"[roadmap/generate] AI error: {e}")
            import traceback; print(traceback.format_exc())
            return jsonify({"error": "AI failed to generate roadmap. Please try again."}), 500

        overview          = result.get("overview", "")
        current_skill_out = result.get("current_skill")

        if not overview:
            return jsonify({"error": "AI returned an empty roadmap. Please try again."}), 500

        stored_payload = json.dumps({
            "overview":      overview,
            "current_skill": current_skill_out,
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
        if current_skill_out:
            response["current_skill"] = current_skill_out

        return jsonify(response), 201

    except Exception as e:
        import traceback
        print(f"[roadmap/generate] error: {e}")
        print(traceback.format_exc())
        return jsonify({"error": "Could not generate roadmap"}), 500

    finally:
        conn.close()


@roadmap_bp.route("/roadmap", methods=["GET"])
@token_required
def get_roadmap():
    """Fetch the student's latest roadmap."""
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