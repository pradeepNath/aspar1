"""
routes/roadmap.py
-----------------
Uses the older roadmap structure with personalized evidence.

Priority:
1. Active learner-specific remediation subskill
2. Normal unlocked core skill
"""

import json
from decimal import Decimal

from flask import Blueprint, jsonify, g

from config.db import get_db_connection
from utils.auth import token_required
from services.groq_service import generate_roadmap

roadmap_bp = Blueprint("roadmap", __name__)


def _make_serializable(obj):
    """
    Recursively convert psycopg2 Decimal (and any other non-JSON-native
    types) into plain Python types, so this data can safely be passed
    into json.dumps() inside generate_roadmap()'s prompt-building.

    NUMERIC/DECIMAL Postgres columns (e.g. the ROUND(...) score query
    below) come back as Decimal via psycopg2 - json.dumps() cannot
    serialize Decimal on its own and raises:
        TypeError: Object of type Decimal is not JSON serializable
    """
    if isinstance(obj, list):
        return [_make_serializable(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def _build_roadmap_context(cursor, user_id, dream, current_level):
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
        SELECT
            id, level, category, skill_name, sequence_order,
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

    # Placement evidence gives the roadmap concrete strengths and gaps rather
    # than forcing it to infer them from an overall score alone.
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

    # Keep the most recently created completed remediation branch in the
    # context too. It lets the roadmap explain the learner's transition
    # back into its parent core skill instead of abruptly sounding generic.
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


@roadmap_bp.route("/roadmap/generate", methods=["POST"])
@token_required
def create_roadmap():
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
                    "error": "Placement not completed yet"
                }), 422

            current_level = level_row["current_level"]

            cursor.execute(
                "SELECT MAX(version) AS max_v FROM roadmaps WHERE user_id = %s",
                (g.user_id,),
            )
            version_row = cursor.fetchone()
            next_version = (version_row["max_v"] or 0) + 1

            context = _build_roadmap_context(
                cursor,
                g.user_id,
                dream,
                current_level,
            )

        try:
            result = generate_roadmap(
                dream=dream,
                academics=context["academics"],
                skill_tree=context["skill_tree"],
                scores=context["scores"],
                placement_evidence=context["placement_evidence"],
                gaps=context["gaps"],
                active_subskill=context["active_subskill"],
                completed_subskill=context["completed_subskill"],
            )
        except Exception as error:
            import traceback
            print(f"[roadmap/generate] AI error: {error}")
            print(traceback.format_exc())
            return jsonify({
                "error": "AI failed to generate roadmap. Please try again."
            }), 500

        overview = result.get("overview", "")
        current_skill = result.get("current_focus")

        if not overview:
            return jsonify({
                "error": "AI returned an empty roadmap. Please try again."
            }), 500

        stored_payload = json.dumps({
            "focus_type": result.get("focus_type"),
            "overview": overview,
            "parent_core_skill": result.get("parent_core_skill"),
            "current_skill": current_skill,
            "next_core_skill": result.get("next_core_skill"),
        })

        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO roadmaps (user_id, roadmap_text, version)
                VALUES (%s, %s, %s)
                """,
                (g.user_id, stored_payload, next_version),
            )

        response = {
            "version": next_version,
            "focus_type": result.get("focus_type"),
            "overview": overview,
            "parent_core_skill": result.get("parent_core_skill"),
            "next_core_skill": result.get("next_core_skill"),
        }

        if current_skill:
            # Kept as current_skill so your existing frontend still works.
            response["current_skill"] = current_skill

        return jsonify(response), 201

    except Exception as error:
        import traceback
        print(f"[roadmap/generate] error: {error}")
        print(traceback.format_exc())
        return jsonify({"error": "Could not generate roadmap"}), 500

    finally:
        conn.close()


@roadmap_bp.route("/roadmap", methods=["GET"])
@token_required
def get_roadmap():
    """Fetch the learner's latest roadmap."""
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
                (g.user_id,),
            )
            row = cursor.fetchone()

        if not row:
            return jsonify({
                "error": "No roadmap found. Generate one first."
            }), 404

        try:
            payload = json.loads(row["roadmap_text"])
        except (TypeError, ValueError):
            payload = {
                "overview": row["roadmap_text"],
                "current_skill": None,
            }

        response = {
            "version": row["version"],
            "focus_type": payload.get("focus_type", "core_skill"),
            "overview": payload.get("overview", ""),
            "parent_core_skill": payload.get("parent_core_skill"),
            "next_core_skill": payload.get("next_core_skill"),
        }

        if payload.get("current_skill"):
            response["current_skill"] = payload["current_skill"]

        if row.get("created_at"):
            response["created_at"] = row["created_at"].isoformat()

        return jsonify(response), 200

    except Exception as error:
        print(f"[roadmap/get] error: {error}")
        return jsonify({"error": "Could not fetch roadmap"}), 500

    finally:
        conn.close()
