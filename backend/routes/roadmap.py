"""
routes/roadmap.py
------------------
Handles roadmap generation and retrieval:

    POST /api/roadmap/generate
        - Gathers full context from DB (dream, academics, skill tree,
          score history, knowledge gaps)
        - Calls generate_roadmap() (AI function 6)
        - Saves result to roadmaps table with an incrementing version
        - Returns the new roadmap

    GET  /api/roadmap
        - Returns the student's latest roadmap

Design note (Section 1 & 10):
    The roadmap tells the student WHAT to learn and what TYPE of
    resource to look for. It never gives specific links, course names,
    or step-by-step instructions. This is enforced at the AI prompt
    level in groq_service.generate_roadmap().

STORAGE NOTE:
    generate_roadmap() now returns a structured object - a short level
    "overview" plus a "current_skill" guide focused on the single
    skill the student should be studying right now (rather than one
    long paragraph covering the whole level). The roadmaps table still
    has a single roadmap_text TEXT column, so the structured result is
    JSON-encoded into that column on save and decoded back out on read.
    This avoids a schema migration while keeping the richer shape.
"""

import json
from flask import Blueprint, request, jsonify, g

from config.db import get_db_connection
from utils.auth import token_required
from services.groq_service import generate_roadmap

roadmap_bp = Blueprint("roadmap", __name__)


# ============================================================
# POST /api/roadmap/generate
# ============================================================
@roadmap_bp.route("/roadmap/generate", methods=["POST"])
@token_required
def create_roadmap():
    """
    Generate (or regenerate) the student's roadmap.

    No body required — all context is pulled from the DB:
      - dream career + academics (student_profiles, academic_results)
      - visible skill tree (current level + below)
      - recent score history (quiz_scores joined with quiz_sessions)
      - knowledge gaps (from the most recent grading session)

    Called:
      - Once right after skill tree generation (first roadmap)
      - Again after every level-up (new level, new roadmap)
      - Again if evaluate_progress() returns 'ease_roadmap' (adjusted
        version for a student who is not improving)

    On success (201):
        {
          "version": 3,
          "overview": "...",
          "current_skill": {
            "skill_name": "...",
            "why_now": "...",
            "what_to_learn": "...",
            "resource_types": ["official documentation", "video tutorials"]
          }
        }

        "current_skill" is omitted if no skill is currently unlocked
        at the student's level (e.g. the whole level is learned and
        they're waiting on the level-up test).
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

            # --- Academics ---
            cursor.execute(
                "SELECT subject, grade, gpa FROM academic_results WHERE user_id = %s",
                (g.user_id,)
            )
            academics = cursor.fetchall()

            # --- Current level ---
            cursor.execute(
                "SELECT current_level FROM skill_levels WHERE user_id = %s AND career = %s",
                (g.user_id, dream)
            )
            level_row = cursor.fetchone()
            if not level_row:
                return jsonify({"error": "Placement not completed yet"}), 422

            current_level = level_row["current_level"]

            # --- Visible skill tree (current level + below) ---
            # status is required so the AI can locate the single
            # "unlocked" skill to build current_skill around.
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

            # --- Recent score history (last 5 graded sessions) ---
            cursor.execute(
                """
                SELECT qs.test_type, qs.level,
                       ROUND(SUM(qsc.score_out_of_10) /
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

            # --- Knowledge gaps from the most recent graded session ---
            # quiz_scores.feedback contains per-question feedback;
            # knowledge gaps are stored in progress_log.notes for level_up,
            # but for a quick context pass to the AI we pull the latest
            # progress_log note if it exists, else empty list.
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

            # notes field stores comma-separated gap topics saved by progress route
            gaps = []
            if log_row and log_row.get("notes"):
                raw_notes = log_row["notes"]
                # If the note starts with "gaps:" it was written by progress.py
                if raw_notes.startswith("gaps:"):
                    gaps = [g.strip() for g in raw_notes[5:].split(",") if g.strip()]

            # --- Next version number ---
            cursor.execute(
                "SELECT MAX(version) AS max_v FROM roadmaps WHERE user_id = %s",
                (g.user_id,)
            )
            ver_row     = cursor.fetchone()
            next_version = (ver_row["max_v"] or 0) + 1

        # --- AI call (function 6) ---
        try:
            result = generate_roadmap(dream, academics, skill_tree, scores, gaps)
        except Exception as e:
            print(f"[roadmap/generate] AI error: {e}")
            return jsonify({"error": "AI failed to generate roadmap. Please try again."}), 500

        overview      = result.get("overview", "")
        current_skill = result.get("current_skill")  # may be None/absent

        if not overview:
            return jsonify({"error": "AI returned an empty roadmap. Please try again."}), 500

        # --- Save to DB (JSON-encoded into the existing TEXT column) ---
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
        return jsonify({"error": "Could not generate roadmap"}), 500

    finally:
        conn.close()


# ============================================================
# GET /api/roadmap
# ============================================================
@roadmap_bp.route("/roadmap", methods=["GET"])
@token_required
def get_roadmap():
    """
    Fetch the student's latest roadmap.

    On success (200):
        {
          "version": 3,
          "overview": "...",
          "current_skill": {
            "skill_name": "...",
            "why_now": "...",
            "what_to_learn": "...",
            "resource_types": ["..."]
          },
          "created_at": "2026-06-13T12:00:00"
        }

        "current_skill" is omitted if none was generated (whole level
        already learned).

    On 404: no roadmap generated yet (frontend should call
    POST /api/roadmap/generate first).
    """
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

        # roadmap_text holds a JSON-encoded {overview, current_skill}
        # payload (see create_roadmap above). Older rows saved before
        # this change may still hold a plain string - fall back
        # gracefully so old data doesn't 500 the route.
        try:
            payload = json.loads(row["roadmap_text"])
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