"""
routes/skills.py
-----------------
Handles the skill tree:

    POST /api/skills/generate
        - Called ONCE after placement grading
        - Calls generate_skill_tree() (AI function 3)
        - Saves all 5 levels to skill_tree
        - Sets correct initial statuses (unlocked/locked/learned)

    GET  /api/skills/tree
        - Returns the visible skill tree (current level + below only)
        - Levels above current are never returned to the frontend

    POST /api/skills/complete
        - Called by grading route logic after a skill_test passes (>=80%)
        - Marks a skill as 'learned', unlocks the next skill in sequence
        - Adds a row to learned_skills
        - Regenerates the roadmap so its "current_skill" panel always
          points at whichever skill is unlocked NOW, not the one that
          was just completed
"""

from flask import Blueprint, request, jsonify, g
import json

from config.db import get_db_connection
from utils.auth import token_required
from services.groq_service import generate_skill_tree, generate_roadmap

skills_bp = Blueprint("skills", __name__)


# ============================================================
# POST /api/skills/generate
# ============================================================
@skills_bp.route("/skills/generate", methods=["POST"])
@token_required
def generate_tree():
    """
    Generate and save the full 5-level skill tree for the student's
    current dream career. Should be called ONCE, right after placement
    grading sets the starting level in skill_levels.

    No body required - all context is read from the DB.

    Guards:
      - If a skill tree already exists for this user+career, returns 409
        to prevent accidental double-generation (the frontend should only
        call this once per career).

    On success (201):
        {
          "message": "Skill tree generated",
          "total_skills": 28,
          "starting_level": 2
        }
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

            # --- Fetch profile ---
            cursor.execute(
                "SELECT dream_career FROM student_profiles WHERE user_id = %s",
                (g.user_id,)
            )
            profile = cursor.fetchone()
            if not profile:
                return jsonify({"error": "Dream career not set"}), 422

            dream = profile["dream_career"]

            # --- Fetch starting level ---
            cursor.execute(
                "SELECT current_level FROM skill_levels WHERE user_id = %s AND career = %s",
                (g.user_id, dream)
            )
            level_row = cursor.fetchone()
            if not level_row:
                return jsonify({"error": "Placement test not completed yet"}), 422

            current_level = level_row["current_level"]

            # --- Guard: don't regenerate if tree exists ---
            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM skill_tree WHERE user_id = %s AND career = %s",
                (g.user_id, dream)
            )
            if cursor.fetchone()["cnt"] > 0:
                return jsonify({"error": "Skill tree already exists for this career"}), 409

            # --- Fetch academics for AI context ---
            cursor.execute(
                "SELECT subject, grade, gpa FROM academic_results WHERE user_id = %s",
                (g.user_id,)
            )
            academics = cursor.fetchall()

        # --- AI call (function 3) ---
        try:
            skills_data = generate_skill_tree(dream, academics, current_level)
        except Exception as e:
            print(f"[skills/generate] AI error: {e}")
            return jsonify({"error": "AI failed to generate skill tree. Please try again."}), 500

        if not isinstance(skills_data, list) or len(skills_data) == 0:
            return jsonify({"error": "AI returned an empty skill tree. Please try again."}), 500

        # --- Determine status for each skill ---
        # Rules from Section 4, step 5:
        #   - Levels BELOW current_level  -> status = 'learned'
        #     (student already placed above them, treat as done)
        #   - current_level, sequence_order == 1 -> status = 'unlocked'
        #     (the very first skill at the student's level is ready to work on)
        #   - everything else at current_level   -> status = 'locked'
        #   - levels ABOVE current_level         -> status = 'locked'
        #
        # sequence_order is assigned by the AI per level; we sort within
        # each level to be safe before applying the unlock logic.

        # Group skills by level to find the minimum sequence_order per level
        skills_by_level = {}
        for s in skills_data:
            lv = s.get("level", 1)
            skills_by_level.setdefault(lv, []).append(s)

        # Sort within each level by sequence_order
        for lv in skills_by_level:
            skills_by_level[lv].sort(key=lambda x: x.get("sequence_order", 0))

        rows_to_insert = []
        for lv, skills in skills_by_level.items():
            for idx, s in enumerate(skills):
                if lv < current_level:
                    status = "learned"
                elif lv == current_level and idx == 0:
                    status = "unlocked"
                else:
                    status = "locked"

                rows_to_insert.append((
                    g.user_id,
                    dream,
                    lv,
                    s.get("category", "General"),
                    s.get("skill_name", "Unknown"),
                    s.get("sequence_order", idx + 1),
                    status,
                ))

        conn2 = get_db_connection()
        try:
            with conn2.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO skill_tree
                        (user_id, career, level, category, skill_name, sequence_order, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    rows_to_insert
                )

                # For skills at levels below current_level that we marked
                # 'learned', also insert into learned_skills so the
                # Progress page can list them.
                cursor.execute(
                    """
                    SELECT id FROM skill_tree
                    WHERE user_id = %s AND career = %s AND status = 'learned'
                    """,
                    (g.user_id, dream)
                )
                learned_ids = cursor.fetchall()

                if learned_ids:
                    learned_rows = [(g.user_id, row["id"]) for row in learned_ids]
                    cursor.executemany(
                        """
                        INSERT IGNORE INTO learned_skills (user_id, skill_id)
                        VALUES (%s, %s)
                        """,
                        learned_rows
                    )
        finally:
            conn2.close()

        return jsonify({
            "message":        "Skill tree generated",
            "total_skills":   len(rows_to_insert),
            "starting_level": current_level,
        }), 201

    except Exception as e:
        print(f"[skills/generate] error: {e}")
        return jsonify({"error": "Could not generate skill tree"}), 500

    finally:
        conn.close()


# ============================================================
# GET /api/skills/tree
# ============================================================
@skills_bp.route("/skills/tree", methods=["GET"])
@token_required
def get_skill_tree():
    """
    Return the visible portion of the skill tree:
      - All levels BELOW current_level (shown as learned/review)
      - The CURRENT level (mix of unlocked/locked/learned)
      - Levels ABOVE current are NOT returned at all

    On success (200):
        {
          "current_level": 2,
          "skills": [
            {
              "id": 5,
              "level": 1,
              "category": "Programming Basics",
              "skill_name": "Variables",
              "sequence_order": 1,
              "status": "learned"
            },
            {
              "id": 12,
              "level": 2,
              "category": "Data Structures",
              "skill_name": "Arrays",
              "sequence_order": 1,
              "status": "unlocked"
            },
            ...
          ]
        }
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

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
            level_row = cursor.fetchone()
            if not level_row:
                return jsonify({"error": "Placement not completed"}), 422

            current_level = level_row["current_level"]

            cursor.execute(
                """
                SELECT id, level, category, skill_name, sequence_order, status
                FROM skill_tree
                WHERE user_id = %s AND career = %s AND level <= %s
                ORDER BY level ASC, sequence_order ASC
                """,
                (g.user_id, dream, current_level)
            )
            skills = cursor.fetchall()

        return jsonify({
            "current_level": current_level,
            "skills":        skills,
        }), 200

    except Exception as e:
        print(f"[skills/tree] error: {e}")
        return jsonify({"error": "Could not fetch skill tree"}), 500

    finally:
        conn.close()


# ============================================================
# POST /api/skills/complete
# ============================================================
@skills_bp.route("/skills/complete", methods=["POST"])
@token_required
def complete_skill():
    """
    Mark a skill as 'learned' and unlock the next skill in sequence.
    Called after a skill_test session is graded with total_score_percent >= 80.

    Expected JSON body:
        { "skill_id": 12 }

    Logic (Section 4, step 8):
      1. Mark skill_id as 'learned' in skill_tree
      2. Insert into learned_skills
      3. Find the next skill in sequence_order within the same level
         - If found: set its status to 'unlocked'
         - If not found (all skills in this level are learned): do nothing
           here - the Level-Up Test trigger is handled by the frontend /
           progress route based on all skills being learned.

    On success (200):
        {
          "message": "Skill marked as learned",
          "next_skill": {          # null if no more skills at this level
            "id": 13,
            "skill_name": "Linked Lists",
            "sequence_order": 2
          }
        }
    """
    data     = request.get_json(silent=True) or {}
    skill_id = data.get("skill_id")

    if not skill_id:
        return jsonify({"error": "skill_id is required"}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

            # Verify the skill belongs to this user and is currently unlocked
            cursor.execute(
                """
                SELECT id, level, sequence_order, career, status
                FROM skill_tree
                WHERE id = %s AND user_id = %s
                """,
                (skill_id, g.user_id)
            )
            skill = cursor.fetchone()

            if not skill:
                return jsonify({"error": "Skill not found"}), 404

            if skill["status"] == "learned":
                return jsonify({"error": "Skill is already marked as learned"}), 409

            level          = skill["level"]
            sequence_order = skill["sequence_order"]
            career         = skill["career"]

            # --- Mark this skill as learned ---
            cursor.execute(
                "UPDATE skill_tree SET status = 'learned' WHERE id = %s",
                (skill_id,)
            )
            cursor.execute(
                "INSERT IGNORE INTO learned_skills (user_id, skill_id) VALUES (%s, %s)",
                (g.user_id, skill_id)
            )

            # --- Find and unlock the next skill in this level ---
            cursor.execute(
                """
                SELECT id, skill_name, sequence_order
                FROM skill_tree
                WHERE user_id = %s AND career = %s AND level = %s
                  AND sequence_order > %s
                ORDER BY sequence_order ASC
                LIMIT 1
                """,
                (g.user_id, career, level, sequence_order)
            )
            next_skill = cursor.fetchone()

            if next_skill:
                cursor.execute(
                    "UPDATE skill_tree SET status = 'unlocked' WHERE id = %s",
                    (next_skill["id"],)
                )

            # --- Regenerate the roadmap around whichever skill is ---
            # --- unlocked now (could be next_skill, or none if the ---
            # --- whole level just got finished) ---------------------
            cursor.execute(
                """
                SELECT subject, grade, gpa FROM academic_results
                WHERE user_id = %s
                """,
                (g.user_id,)
            )
            academics = cursor.fetchall()

            cursor.execute(
                """
                SELECT level, category, skill_name, sequence_order, status
                FROM skill_tree
                WHERE user_id = %s AND career = %s AND level <= %s
                ORDER BY level ASC, sequence_order ASC
                """,
                (g.user_id, career, level)
            )
            visible_skill_tree = cursor.fetchall()

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
            if log_row and log_row.get("notes", "").startswith("gaps:"):
                gaps = [g2.strip() for g2 in log_row["notes"][5:].split(",") if g2.strip()]

            cursor.execute(
                "SELECT MAX(version) AS max_v FROM roadmaps WHERE user_id = %s",
                (g.user_id,)
            )
            ver_row      = cursor.fetchone()
            next_version = (ver_row["max_v"] or 0) + 1

        # --- AI call to regenerate the roadmap (separate connection, ---
        # --- same pattern used by routes/roadmap.py and progress.py) ---
        try:
            rm = generate_roadmap(career, academics, visible_skill_tree, [], gaps)
            stored_payload = json.dumps({
                "overview":      rm.get("overview", ""),
                "current_skill": rm.get("current_skill"),
            })
            conn2 = get_db_connection()
            try:
                with conn2.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO roadmaps (user_id, roadmap_text, version) VALUES (%s, %s, %s)",
                        (g.user_id, stored_payload, next_version)
                    )
            finally:
                conn2.close()
        except Exception as e:
            # Roadmap regeneration failing shouldn't block the skill
            # completion from being recorded - log and continue. The
            # student keeps their progress; the dashboard will just
            # show a slightly stale roadmap until the next successful
            # generation (e.g. their next skill test or level-up).
            print(f"[skills/complete] roadmap regen error: {e}")

        return jsonify({
            "message":    "Skill marked as learned",
            "next_skill": next_skill,
        }), 200

    except Exception as e:
        print(f"[skills/complete] error: {e}")
        return jsonify({"error": "Could not complete skill"}), 500

    finally:
        conn.close()