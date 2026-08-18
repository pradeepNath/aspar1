"""
routes/skills.py
-----------------
UPDATED generate_tree() to:
1. Save skill_type and skill_category from the new AI response shape
2. Save dependencies to skill_dependencies table
3. Validate dependencies before saving (no circular refs, must exist)

UPDATED complete_skill() to:
1. Use the new generate_roadmap(dream, current_skill, learner_model) signature
"""

from flask import Blueprint, request, jsonify, g
import json

from config.db import get_db_connection
from utils.auth import token_required
from services.groq_service import generate_skill_tree, generate_roadmap
from services.gap_analysis import get_learner_model

skills_bp = Blueprint("skills", __name__)


def _validate_and_save_dependencies(cursor, user_id, career, name_to_id, dependencies):
    """
    Validate AI-suggested dependencies before saving.
    - Both skills must exist in name_to_id
    - No self-dependency
    - No duplicate
    (Circular dependency check across chains is skipped here since the
     universal tree is generated once and levels enforce ordering —
     but we do prevent direct A->A and A<->B mutual pairs.)
    """
    seen_pairs = set()
    valid_rows = []

    for dep in dependencies:
        skill_name = dep.get("skill_name")
        depends_on = dep.get("depends_on")

        if not skill_name or not depends_on:
            continue
        if skill_name == depends_on:
            continue  # no self-dependency

        skill_id = name_to_id.get(skill_name)
        prereq_id = name_to_id.get(depends_on)

        if not skill_id or not prereq_id:
            continue  # referenced a skill that doesn't exist — skip

        pair = (skill_id, prereq_id)
        reverse_pair = (prereq_id, skill_id)

        if pair in seen_pairs or reverse_pair in seen_pairs:
            continue  # duplicate or mutual circular pair

        seen_pairs.add(pair)
        valid_rows.append((skill_id, prereq_id))

    if valid_rows:
        cursor.executemany(
            """
            INSERT INTO skill_dependencies (skill_id, prerequisite_skill_id)
            VALUES (%s, %s)
            ON CONFLICT (skill_id, prerequisite_skill_id) DO NOTHING
            """,
            valid_rows
        )

    return len(valid_rows)


@skills_bp.route("/skills/generate", methods=["POST"])
@token_required
def generate_tree():
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
                "SELECT current_level FROM skill_levels WHERE user_id = %s AND career = %s",
                (g.user_id, dream)
            )
            level_row = cursor.fetchone()
            if not level_row:
                return jsonify({"error": "Placement test not completed yet"}), 422
            current_level = level_row["current_level"]

            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM skill_tree WHERE user_id = %s AND career = %s",
                (g.user_id, dream)
            )
            if cursor.fetchone()["cnt"] > 0:
                return jsonify({"error": "Skill tree already exists for this career"}), 409

            cursor.execute(
                "SELECT subject, grade, gpa FROM academic_results WHERE user_id = %s",
                (g.user_id,)
            )
            academics = cursor.fetchall()

        # --- AI call — now returns {skills, dependencies} ---
        try:
            ai_result = generate_skill_tree(dream, academics, current_level)
        except Exception as e:
            print(f"[skills/generate] AI error: {e}")
            return jsonify({"error": "AI failed to generate skill tree. Please try again."}), 500

        skills_data   = ai_result.get("skills", []) if isinstance(ai_result, dict) else ai_result
        dependencies  = ai_result.get("dependencies", []) if isinstance(ai_result, dict) else []

        if not isinstance(skills_data, list) or len(skills_data) == 0:
            return jsonify({"error": "AI returned an empty skill tree. Please try again."}), 500

        # Group and sort by level/sequence
        skills_by_level = {}
        for s in skills_data:
            lv = s.get("level", 1)
            skills_by_level.setdefault(lv, []).append(s)
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
                    s.get("skill_type", "mixed"),
                    s.get("skill_category", "core"),
                ))

        conn2 = get_db_connection()
        try:
            with conn2.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO skill_tree
                        (user_id, career, level, category, skill_name,
                         sequence_order, status, skill_type, skill_category)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    rows_to_insert
                )

                # Mark below-level skills as learned in learned_skills
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
                        INSERT INTO learned_skills (user_id, skill_id)
                        VALUES (%s, %s)
                        ON CONFLICT (user_id, skill_id) DO NOTHING
                        """,
                        learned_rows
                    )

                # --- Save dependencies ---
                cursor.execute(
                    "SELECT id, skill_name FROM skill_tree WHERE user_id = %s AND career = %s",
                    (g.user_id, dream)
                )
                name_to_id = {row["skill_name"]: row["id"] for row in cursor.fetchall()}

                deps_saved = _validate_and_save_dependencies(
                    cursor, g.user_id, dream, name_to_id, dependencies
                )

        finally:
            conn2.close()

        return jsonify({
            "message":            "Skill tree generated",
            "total_skills":       len(rows_to_insert),
            "starting_level":     current_level,
            "dependencies_saved": deps_saved,
        }), 201

    except Exception as e:
        import traceback
        print(f"[skills/generate] error: {e}")
        print(traceback.format_exc())
        return jsonify({"error": "Could not generate skill tree"}), 500

    finally:
        conn.close()


@skills_bp.route("/skills/tree", methods=["GET"])
@token_required
def get_skill_tree():
    """
    Return the visible skill tree PLUS dependency edges for the
    frontend to draw the visual graph.
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
                SELECT id, level, category, skill_name, sequence_order,
                       status, skill_type, skill_category
                FROM skill_tree
                WHERE user_id = %s AND career = %s AND level <= %s
                ORDER BY level ASC, sequence_order ASC
                """,
                (g.user_id, dream, current_level)
            )
            skills = cursor.fetchall()

            visible_ids = [s["id"] for s in skills]
            edges = []
            if visible_ids:
                placeholders = ",".join(["%s"] * len(visible_ids))
                cursor.execute(
                    f"""
                    SELECT skill_id, prerequisite_skill_id
                    FROM skill_dependencies
                    WHERE skill_id IN ({placeholders})
                       OR prerequisite_skill_id IN ({placeholders})
                    """,
                    visible_ids + visible_ids
                )
                edges = [
                    {"from": row["prerequisite_skill_id"], "to": row["skill_id"]}
                    for row in cursor.fetchall()
                ]

        return jsonify({
            "current_level": current_level,
            "skills":        skills,
            "dependencies":  edges,
        }), 200

    except Exception as e:
        print(f"[skills/tree] error: {e}")
        return jsonify({"error": "Could not fetch skill tree"}), 500

    finally:
        conn.close()


@skills_bp.route("/skills/complete", methods=["POST"])
@token_required
def complete_skill():
    data     = request.get_json(silent=True) or {}
    skill_id = data.get("skill_id")

    if not skill_id:
        return jsonify({"error": "skill_id is required"}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

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

            cursor.execute(
                "UPDATE skill_tree SET status = 'learned' WHERE id = %s",
                (skill_id,)
            )
            cursor.execute(
                """
                INSERT INTO learned_skills (user_id, skill_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, skill_id) DO NOTHING
                """,
                (g.user_id, skill_id)
            )

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

            # --- Fetch current unlocked skill's full info for roadmap ---
            current_skill = None
            if next_skill:
                cursor.execute(
                    "SELECT skill_name, skill_type, category FROM skill_tree WHERE id = %s",
                    (next_skill["id"],)
                )
                current_skill = dict(cursor.fetchone())

            cursor.execute(
                "SELECT MAX(version) AS max_v FROM roadmaps WHERE user_id = %s",
                (g.user_id,)
            )
            ver_row      = cursor.fetchone()
            next_version = (ver_row["max_v"] or 0) + 1

        # --- Regenerate roadmap using learner model ---
        try:
            learner_model = get_learner_model(conn, g.user_id)
            rm = generate_roadmap(career, current_skill, learner_model)
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
            print(f"[skills/complete] roadmap regen error: {e}")
            import traceback; print(traceback.format_exc())

        return jsonify({
            "message":    "Skill marked as learned",
            "next_skill": next_skill,
        }), 200

    except Exception as e:
        import traceback
        print(f"[skills/complete] error: {e}")
        print(traceback.format_exc())
        return jsonify({"error": "Could not complete skill"}), 500

    finally:
        conn.close()