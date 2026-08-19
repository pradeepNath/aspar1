"""
routes/skills.py
----------------
Shared core curriculum + learner-specific progress.

career_core_skills  = same standard curriculum for one career
skill_tree          = each learner's progress/status copy
adaptive_skills     = learner-only remediation subskills
"""

import json
from decimal import Decimal

from flask import Blueprint, request, jsonify, g

from config.db import get_db_connection
from utils.auth import token_required
from services.curriculum_service import assign_tree_to_learner
from services.groq_service import generate_roadmap

skills_bp = Blueprint("skills", __name__)


def _make_serializable(obj):
    """
    Recursively convert psycopg2 Decimal (and any other non-JSON-native
    types) into plain Python types, so this data can safely be passed
    into json.dumps() inside generate_roadmap()'s prompt-building.

    NUMERIC/DECIMAL Postgres columns (e.g. the ROUND(...) score query
    below) come back as Decimal via psycopg2 - json.dumps() cannot
    serialize Decimal on its own and raises:
        TypeError: Object of type Decimal is not JSON serializable

    Kept identical to routes/roadmap.py's copy of this helper - both
    call generate_roadmap() with the same shape of data. If this drifts
    out of sync again, consider moving it to a shared
    utils/serialization.py instead.
    """
    if isinstance(obj, list):
        return [_make_serializable(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def _roadmap_context(cursor, user_id, dream, current_level):
    """Build the data required by the older-style personalized roadmap."""

    cursor.execute(
        """
        SELECT subject, grade, gpa
        FROM academic_results
        WHERE user_id = %s
        ORDER BY uploaded_at ASC
        """,
        (user_id,),
    )
    academics = _make_serializable(cursor.fetchall())

    cursor.execute(
        """
        SELECT id, level, category, skill_name, sequence_order,
               status, skill_type, skill_category
        FROM skill_tree
        WHERE user_id = %s
          AND career = %s
          AND level <= %s
        ORDER BY level ASC, sequence_order ASC
        """,
        (user_id, dream, current_level),
    )
    skill_tree = _make_serializable([dict(row) for row in cursor.fetchall()])

    cursor.execute(
        """
        SELECT
            qs.id AS session_id,
            qs.test_type,
            ROUND(
                CAST(SUM(sc.score_out_of_10) AS NUMERIC)
                / (COUNT(sc.id) * 10.0) * 100,
                1
            ) AS total_score_percent
        FROM quiz_sessions qs
        JOIN quiz_scores sc ON sc.session_id = qs.id
        WHERE qs.user_id = %s
        GROUP BY qs.id, qs.test_type
        ORDER BY qs.id DESC
        LIMIT 10
        """,
        (user_id,),
    )
    scores = _make_serializable([dict(row) for row in cursor.fetchall()])

    cursor.execute(
        """
        SELECT
            qq.question_text,
            qq.concept,
            sc.score_out_of_10
        FROM quiz_sessions qs
        JOIN quiz_questions qq ON qq.session_id = qs.id
        JOIN quiz_scores sc ON sc.session_id = qs.id AND sc.question_id = qq.id
        WHERE qs.id = (
            SELECT id FROM quiz_sessions
            WHERE user_id = %s AND test_type = 'placement'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        )
        ORDER BY qq.question_number ASC
        """,
        (user_id,),
    )
    placement_evidence = _make_serializable(
        [dict(row) for row in cursor.fetchall()]
    )

    cursor.execute(
        """
        SELECT weak_concepts
        FROM skill_gap_analysis
        WHERE user_id = %s
        ORDER BY analyzed_at DESC
        LIMIT 10
        """,
        (user_id,),
    )

    gaps = []
    for row in cursor.fetchall():
        try:
            weak_concepts = json.loads(row["weak_concepts"] or "[]")
            gaps.extend(
                item.get("concept")
                for item in weak_concepts
                if item.get("concept")
            )
        except (TypeError, ValueError):
            pass

    gaps = list(dict.fromkeys(gaps))

    cursor.execute(
        """
        SELECT
            a.id,
            a.skill_name,
            a.concept,
            a.skill_type,
            a.reason,
            st.skill_name AS parent_core_skill
        FROM adaptive_skills a
        JOIN skill_tree st ON st.id = a.parent_skill_id
        WHERE a.user_id = %s
          AND a.status = 'unlocked'
        ORDER BY a.created_at ASC
        LIMIT 1
        """,
        (user_id,),
    )
    active_subskill = cursor.fetchone()

    cursor.execute(
        """
        SELECT
            a.id,
            a.skill_name,
            a.concept,
            a.skill_type,
            a.reason,
            st.skill_name AS parent_core_skill
        FROM adaptive_skills a
        JOIN skill_tree st ON st.id = a.parent_skill_id
        WHERE a.user_id = %s
          AND a.status = 'learned'
          AND st.status = 'unlocked'
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    completed_subskill = cursor.fetchone()

    return {
        "academics": academics,
        "skill_tree": skill_tree,
        "scores": scores,
        "placement_evidence": placement_evidence,
        "gaps": gaps,
        "active_subskill": (
            _make_serializable(dict(active_subskill))
            if active_subskill else None
        ),
        "completed_subskill": (
            _make_serializable(dict(completed_subskill))
            if completed_subskill else None
        ),
    }


@skills_bp.route("/skills/generate", methods=["POST"])
@token_required
def generate_tree():
    """
    Assign the stored standardized tree to this learner.

    Groq is called only when this career has no stored core tree yet.
    """
    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT dream_career
                FROM student_profiles
                WHERE user_id = %s
                """,
                (g.user_id,),
            )
            profile = cursor.fetchone()

            if not profile:
                return jsonify({"error": "Dream career not set"}), 422

            dream = profile["dream_career"]

            cursor.execute(
                """
                SELECT current_level
                FROM skill_levels
                WHERE user_id = %s AND career = %s
                """,
                (g.user_id, dream),
            )
            level_row = cursor.fetchone()

            if not level_row:
                return jsonify({
                    "error": "Placement test not completed yet"
                }), 422

            current_level = level_row["current_level"]

        assign_tree_to_learner(
            conn=conn,
            user_id=g.user_id,
            dream=dream,
            starting_level=current_level,
        )

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS total_skills
                FROM skill_tree
                WHERE user_id = %s AND career = %s
                """,
                (g.user_id, dream),
            )
            total_skills = cursor.fetchone()["total_skills"]

        return jsonify({
            "message": "Standardized core skill tree assigned",
            "total_skills": total_skills,
            "starting_level": current_level,
        }), 201

    except Exception as error:
        import traceback
        print(f"[skills/generate] error: {error}")
        print(traceback.format_exc())
        return jsonify({"error": "Could not generate skill tree"}), 500

    finally:
        conn.close()


@skills_bp.route("/skills/tree", methods=["GET"])
@token_required
def get_skill_tree():
    """Return visible core skills plus learner-specific remediation skills."""
    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT dream_career
                FROM student_profiles
                WHERE user_id = %s
                """,
                (g.user_id,),
            )
            profile = cursor.fetchone()

            if not profile:
                return jsonify({"error": "Profile not found"}), 422

            dream = profile["dream_career"]

            cursor.execute(
                """
                SELECT current_level
                FROM skill_levels
                WHERE user_id = %s AND career = %s
                """,
                (g.user_id, dream),
            )
            level_row = cursor.fetchone()

            if not level_row:
                return jsonify({"error": "Placement not completed"}), 422

            current_level = level_row["current_level"]

            cursor.execute(
                """
                SELECT
                    id, core_skill_id, level, category, skill_name,
                    sequence_order, status, skill_type, skill_category
                FROM skill_tree
                WHERE user_id = %s
                  AND career = %s
                  AND level <= %s
                ORDER BY level ASC, sequence_order ASC
                """,
                (g.user_id, dream, current_level),
            )
            skills = cursor.fetchall()

            visible_ids = [skill["id"] for skill in skills]

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
                    visible_ids + visible_ids,
                )
                edges = [
                    {
                        "from": row["prerequisite_skill_id"],
                        "to": row["skill_id"],
                    }
                    for row in cursor.fetchall()
                ]

            cursor.execute(
                """
                SELECT
                    a.id,
                    a.parent_skill_id,
                    a.concept,
                    a.skill_name,
                    a.skill_type,
                    a.reason,
                    a.status,
                    a.created_at
                FROM adaptive_skills a
                WHERE a.user_id = %s
                ORDER BY
                    CASE WHEN a.status = 'unlocked' THEN 0 ELSE 1 END,
                    a.created_at ASC
                """,
                (g.user_id,),
            )
            personalized_subskills = cursor.fetchall()

        return jsonify({
            "current_level": current_level,
            "skills": skills,
            "dependencies": edges,
            "personalized_subskills": personalized_subskills,
        }), 200

    except Exception as error:
        print(f"[skills/tree] error: {error}")
        return jsonify({"error": "Could not fetch skill tree"}), 500

    finally:
        conn.close()


@skills_bp.route("/skills/complete", methods=["POST"])
@token_required
def complete_skill():
    """
    Complete one core skill.

    A core skill cannot be completed while it has an unfinished
    personalized remediation subskill.
    """
    data = request.get_json(silent=True) or {}
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
                (skill_id, g.user_id),
            )
            skill = cursor.fetchone()

            if not skill:
                return jsonify({"error": "Skill not found"}), 404

            if skill["status"] == "learned":
                return jsonify({
                    "error": "Skill is already marked as learned"
                }), 409

            if skill["status"] != "unlocked":
                return jsonify({
                    "error": "This skill is not unlocked yet"
                }), 409

            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM adaptive_skills
                WHERE user_id = %s
                  AND parent_skill_id = %s
                  AND status = 'unlocked'
                """,
                (g.user_id, skill_id),
            )

            if cursor.fetchone()["count"] > 0:
                return jsonify({
                    "error": (
                        "Complete the personalized remediation subskills "
                        "before progressing from this core skill."
                    )
                }), 409

            level = skill["level"]
            sequence_order = skill["sequence_order"]
            career = skill["career"]

            cursor.execute(
                "UPDATE skill_tree SET status = 'learned' WHERE id = %s",
                (skill_id,),
            )

            cursor.execute(
                """
                INSERT INTO learned_skills (user_id, skill_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, skill_id) DO NOTHING
                """,
                (g.user_id, skill_id),
            )

            cursor.execute(
                """
                SELECT id, skill_name, sequence_order
                FROM skill_tree
                WHERE user_id = %s
                  AND career = %s
                  AND level = %s
                  AND sequence_order > %s
                ORDER BY sequence_order ASC
                LIMIT 1
                """,
                (g.user_id, career, level, sequence_order),
            )
            next_skill = cursor.fetchone()

            if next_skill:
                cursor.execute(
                    """
                    UPDATE skill_tree
                    SET status = 'unlocked'
                    WHERE id = %s
                    """,
                    (next_skill["id"],),
                )

            cursor.execute(
                """
                SELECT current_level
                FROM skill_levels
                WHERE user_id = %s AND career = %s
                """,
                (g.user_id, career),
            )
            level_row = cursor.fetchone()
            current_level = (
                level_row["current_level"] if level_row else level
            )

            cursor.execute(
                "SELECT MAX(version) AS max_v FROM roadmaps WHERE user_id = %s",
                (g.user_id,),
            )
            version_row = cursor.fetchone()
            next_version = (version_row["max_v"] or 0) + 1

            context = _roadmap_context(
                cursor,
                g.user_id,
                career,
                current_level,
            )

        try:
            roadmap = generate_roadmap(
                dream=career,
                academics=context["academics"],
                skill_tree=context["skill_tree"],
                scores=context["scores"],
                placement_evidence=context["placement_evidence"],
                gaps=context["gaps"],
                active_subskill=context["active_subskill"],
                completed_subskill=context["completed_subskill"],
            )

            stored_payload = json.dumps({
                "focus_type": roadmap.get("focus_type"),
                "overview": roadmap.get("overview", ""),
                "parent_core_skill": roadmap.get("parent_core_skill"),
                "current_skill": roadmap.get("current_focus"),
                "next_core_skill": roadmap.get("next_core_skill"),
            })

            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO roadmaps (user_id, roadmap_text, version)
                    VALUES (%s, %s, %s)
                    """,
                    (g.user_id, stored_payload, next_version),
                )

        except Exception as error:
            import traceback
            print(f"[skills/complete] roadmap error: {error}")
            print(traceback.format_exc())

        return jsonify({
            "message": "Skill marked as learned",
            "next_skill": next_skill,
        }), 200

    except Exception as error:
        import traceback
        print(f"[skills/complete] error: {error}")
        print(traceback.format_exc())
        return jsonify({"error": "Could not complete skill"}), 500

    finally:
        conn.close()
