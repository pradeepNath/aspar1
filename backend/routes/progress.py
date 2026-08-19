"""
routes/progress.py
-------------------
UPDATED: roadmap regeneration after level-up now uses the learner
model + current_skill signature instead of the old flat params.
"""

import json
from decimal import Decimal
from flask import Blueprint, request, jsonify, g

from config.db import get_db_connection
from utils.auth import token_required
from services.groq_service import evaluate_progress, generate_roadmap
from routes.roadmap import _build_roadmap_context

progress_bp = Blueprint("progress", __name__)

FAILURE_STREAK_THRESHOLD = 3


@progress_bp.route("/progress/evaluate", methods=["POST"])
@token_required
def evaluate():
    data                = request.get_json(silent=True) or {}
    session_id          = data.get("session_id")
    total_score_percent = data.get("total_score_percent")
    knowledge_gaps      = data.get("knowledge_gaps", [])

    if not session_id:
        return jsonify({"error": "session_id is required"}), 400
    if total_score_percent is None:
        return jsonify({"error": "total_score_percent is required"}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT id, level, attempt_number
                FROM quiz_sessions
                WHERE id = %s AND user_id = %s AND test_type = 'level_up'
                """,
                (session_id, g.user_id)
            )
            session = cursor.fetchone()
            if not session:
                return jsonify({"error": "Level-up session not found"}), 404

            current_level  = session["level"]
            attempt_number = session["attempt_number"]

            cursor.execute(
                "SELECT dream_career FROM student_profiles WHERE user_id = %s",
                (g.user_id,)
            )
            profile = cursor.fetchone()
            dream   = profile["dream_career"] if profile else ""

            cursor.execute(
                """
                SELECT total_score, status
                FROM progress_log
                WHERE user_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (g.user_id,)
            )
            prev_row       = cursor.fetchone()
            previous_score = float(prev_row["total_score"]) if prev_row else None

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
            for s in recent_scores:
                if s is not None and float(s) < 80:
                    consecutive_failures += 1
                else:
                    break

            cursor.execute(
                """
                SELECT status FROM progress_log
                WHERE user_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT 10
                """,
                (g.user_id,)
            )
            recent_statuses = [r["status"] for r in cursor.fetchall()]
            consecutive_no_improvement = 0
            for s in recent_statuses:
                if s == "eased":
                    consecutive_no_improvement += 1
                else:
                    break

        try:
            eval_result = evaluate_progress(
                previous_score, total_score_percent, current_level,
                consecutive_no_improvement,
            )
        except Exception as e:
            print(f"[progress/evaluate] AI error: {e}")
            return jsonify({"error": "Progress evaluation failed. Please try again."}), 500

        decision  = eval_result.get("decision", "retain")
        reasoning = eval_result.get("reasoning", "")

        this_attempt_failed = total_score_percent < 80
        effective_streak    = consecutive_failures + (1 if this_attempt_failed else 0)

        if this_attempt_failed and effective_streak >= FAILURE_STREAK_THRESHOLD and decision != "level_up":
            decision = "flag_unfit"
            if not reasoning:
                reasoning = (
                    f"You've now had {effective_streak} level-up attempts in a row below "
                    "the 80% pass mark. It may be worth exploring a career path that better "
                    "matches your current strengths."
                )

        new_level  = current_level
        flag_unfit = decision == "flag_unfit"

        status_map = {
            "level_up":     "leveled_up",
            "retain":       "retained",
            "ease_roadmap": "eased",
            "flag_unfit":   "eased",
        }
        log_status = status_map.get(decision, "retained")

        conn3 = get_db_connection()
        try:
            with conn3.cursor() as cursor:

                if decision == "level_up" and current_level < 5:
                    new_level = current_level + 1
                    cursor.execute(
                        """
                        UPDATE skill_levels SET current_level = %s
                        WHERE user_id = %s AND career = %s
                        """,
                        (new_level, g.user_id, dream)
                    )
                    cursor.execute(
                        """
                        SELECT id FROM skill_tree
                        WHERE user_id = %s AND career = %s AND level = %s
                        ORDER BY sequence_order ASC
                        LIMIT 1
                        """,
                        (g.user_id, dream, new_level)
                    )
                    first_skill = cursor.fetchone()
                    if first_skill:
                        cursor.execute(
                            "UPDATE skill_tree SET status = 'unlocked' WHERE id = %s",
                            (first_skill["id"],)
                        )

                notes_str = ""
                if knowledge_gaps:
                    notes_str = "gaps:" + ",".join(knowledge_gaps)

                cursor.execute(
                    """
                    INSERT INTO progress_log
                        (user_id, attempt_number, total_score, previous_score,
                         level, status, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        g.user_id, attempt_number, total_score_percent,
                        previous_score, current_level, log_status, notes_str,
                    )
                )

                # --- Regenerate roadmap with new signature ---
                if decision in ("level_up", "ease_roadmap"):
                    cursor.execute(
                        "SELECT MAX(version) AS max_v FROM roadmaps WHERE user_id = %s",
                        (g.user_id,)
                    )
                    ver_row      = cursor.fetchone()
                    next_version = (ver_row["max_v"] or 0) + 1
                    context = _build_roadmap_context(
                        cursor, g.user_id, dream, new_level
                    )

                    try:
                        rm = generate_roadmap(
                            dream=dream,
                            academics=context["academics"],
                            skill_tree=context["skill_tree"],
                            scores=context["scores"],
                            placement_evidence=context["placement_evidence"],
                            gaps=context["gaps"],
                            active_subskill=context["active_subskill"],
                            completed_subskill=context["completed_subskill"],
                        )
                        stored_payload = json.dumps({
                            "focus_type": rm.get("focus_type"),
                            "overview": rm.get("overview", ""),
                            "parent_core_skill": rm.get("parent_core_skill"),
                            "current_skill": rm.get("current_focus"),
                            "next_core_skill": rm.get("next_core_skill"),
                        })
                        cursor.execute(
                            "INSERT INTO roadmaps (user_id, roadmap_text, version) VALUES (%s, %s, %s)",
                            (g.user_id, stored_payload, next_version)
                        )
                    except Exception as e:
                        print(f"[progress/evaluate] roadmap regen error: {e}")
                        import traceback; print(traceback.format_exc())

        finally:
            conn3.close()

        return jsonify({
            "decision":       decision,
            "reasoning":      reasoning,
            "previous_level": current_level,
            "new_level":      new_level,
            "attempt_number": attempt_number,
            "flag_unfit":     flag_unfit,
        }), 200

    except Exception as e:
        import traceback
        print(f"[progress/evaluate] error: {e}")
        print(traceback.format_exc())
        return jsonify({"error": "Progress evaluation failed unexpectedly"}), 500

    finally:
        conn.close()


@progress_bp.route("/progress/log", methods=["GET"])
@token_required
def get_progress_log():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT sp.dream_career, sl.current_level
                FROM student_profiles sp
                JOIN skill_levels sl ON sl.user_id = sp.user_id
                                     AND sl.career = sp.dream_career
                WHERE sp.user_id = %s
                """,
                (g.user_id,)
            )
            level_info    = cursor.fetchone()
            current_level = level_info["current_level"] if level_info else 1

            cursor.execute(
                """
                SELECT attempt_number, total_score, previous_score,
                       level, status, created_at
                FROM progress_log
                WHERE user_id = %s
                ORDER BY created_at ASC, id ASC
                """,
                (g.user_id,)
            )
            log_rows = cursor.fetchall()
            for row in log_rows:
                if row.get("created_at"):
                    row["created_at"] = row["created_at"].isoformat()
                if row.get("total_score") is not None:
                    row["total_score"] = float(row["total_score"])
                if row.get("previous_score") is not None:
                    row["previous_score"] = float(row["previous_score"])

            cursor.execute(
                """
                SELECT ls.skill_id, st.skill_name, st.category, st.level, ls.learned_at
                FROM learned_skills ls
                JOIN skill_tree st ON st.id = ls.skill_id
                WHERE ls.user_id = %s
                ORDER BY st.level ASC, st.sequence_order ASC
                """,
                (g.user_id,)
            )
            learned = cursor.fetchall()
            for row in learned:
                if row.get("learned_at"):
                    row["learned_at"] = row["learned_at"].isoformat()

        return jsonify({
            "current_level":  current_level,
            "progress_log":   log_rows,
            "learned_skills": learned,
        }), 200

    except Exception as e:
        print(f"[progress/log] error: {e}")
        return jsonify({"error": "Could not fetch progress log"}), 500

    finally:
        conn.close()
