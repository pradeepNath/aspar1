"""
routes/progress.py
-------------------
Handles level-up evaluation and progress tracking:

    POST /api/progress/evaluate
        - Called after a level_up test is graded
        - Calls evaluate_progress() (AI function 7)
        - Acts on the decision: level_up / retain / ease_roadmap / flag_unfit
        - Writes to progress_log
        - If levelled up: increments current_level, unlocks next level's
          first skill, regenerates roadmap
        - Returns the decision + any updated state

    GET  /api/progress/log
        - Returns the full progress_log for the student (for graph)
        - Also returns the list of all learned skills
"""

from flask import Blueprint, request, jsonify, g
import json

from config.db import get_db_connection
from utils.auth import token_required
from services.groq_service import evaluate_progress, generate_roadmap

progress_bp = Blueprint("progress", __name__)


# ============================================================
# POST /api/progress/evaluate
# ============================================================
@progress_bp.route("/progress/evaluate", methods=["POST"])
@token_required
def evaluate():
    """
    Run progress evaluation after a level_up test session is graded.

    Expected JSON body:
        {
          "session_id": 14,
          "total_score_percent": 85.0,
          "knowledge_gaps": ["Recursion", "Big-O"]
        }

    Flow:
        1. Fetch previous score + consecutive_no_improvement count
           from progress_log
        2. Call evaluate_progress() (AI function 7)
        3. Act on decision:
             level_up      -> current_level += 1, unlock first skill of
                              new level, regenerate roadmap
             retain        -> no level change, roadmap unchanged
             ease_roadmap  -> no level change, regenerate roadmap with
                              same context (AI prompt will make it easier)
             flag_unfit    -> mark in progress_log, frontend shows
                              career-change offer
        4. Write progress_log row
        5. Return decision + updated level

    On success (200):
        {
          "decision": "level_up",
          "reasoning": "...",
          "previous_level": 2,
          "new_level": 3,          # same as previous if not levelled up
          "attempt_number": 4,
          "flag_unfit": false
        }
    """
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

            # --- Verify session belongs to user and is level_up type ---
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

            # --- Fetch profile for career ---
            cursor.execute(
                "SELECT dream_career FROM student_profiles WHERE user_id = %s",
                (g.user_id,)
            )
            profile = cursor.fetchone()
            dream   = profile["dream_career"] if profile else ""

            # --- Previous score from progress_log ---
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
            previous_score = prev_row["total_score"] if prev_row else None

            # --- Count recent FAILED attempts (score < 80%), not just ---
            # --- "no improvement" - this is the metric that actually ---
            # --- reflects whether the student is struggling. ----------
            # NOTE: we deliberately do NOT rely on consecutive
            # "improvement" streaks here. A student whose scores
            # genuinely fluctuate (45% -> 50% -> 40% -> 55%) can show
            # "improvement" on some attempts yet still be failing to
            # pass every single time - tracking only consecutive
            # non-improvement let real struggling students slip through
            # without ever reaching the threshold. Counting consecutive
            # FAILED-TO-PASS attempts (score < 80%) is the metric that
            # actually matches the real-world signal: "this student
            # keeps failing the level-up test."
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
                if s is not None and s < 80:
                    consecutive_failures += 1
                else:
                    break

            # consecutive_no_improvement is still computed and passed to
            # the AI as extra context for its written reasoning, but it
            # no longer GATES the flag_unfit decision on its own - see
            # the FAILURE_STREAK_THRESHOLD override below.
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

        # How many consecutive failed (< 80%) level-up attempts before
        # we force flag_unfit, regardless of what the AI decides. This
        # is a hard, code-enforced rule rather than something the LLM
        # is merely asked to follow - the AI's job is to provide the
        # human-readable reasoning, not to gatekeep this decision.
        FAILURE_STREAK_THRESHOLD = 3

        # --- AI evaluation call (function 7) ---
        try:
            eval_result = evaluate_progress(
                previous_score,
                total_score_percent,
                current_level,
                consecutive_no_improvement,
            )
        except Exception as e:
            print(f"[progress/evaluate] AI error: {e}")
            return jsonify({"error": "Progress evaluation failed. Please try again."}), 500

        decision  = eval_result.get("decision", "retain")
        reasoning = eval_result.get("reasoning", "")

        # --- Hard override: this attempt's own failure counts toward ---
        # --- the streak too, so check it BEFORE acting on the decision ---
        this_attempt_failed = total_score_percent < 80
        effective_streak = consecutive_failures + (1 if this_attempt_failed else 0)

        if this_attempt_failed and effective_streak >= FAILURE_STREAK_THRESHOLD and decision != "level_up":
            if decision != "flag_unfit":
                print(
                    f"[progress/evaluate] overriding AI decision '{decision}' -> "
                    f"'flag_unfit' (user_id={g.user_id}, effective_streak={effective_streak})"
                )
            decision = "flag_unfit"
            if not reasoning:
                reasoning = (
                    f"You've now had {effective_streak} level-up attempts in a row below "
                    "the 80% pass mark. It may be worth exploring a career path that better "
                    "matches your current strengths."
                )

        new_level  = current_level
        flag_unfit = decision == "flag_unfit"

        # Map decision to progress_log status strings
        status_map = {
            "level_up":    "leveled_up",
            "retain":      "retained",
            "ease_roadmap":"eased",
            "flag_unfit":  "eased",   # still counts as no improvement
        }
        log_status = status_map.get(decision, "retained")

        # --- Act on decision ---
        conn3 = get_db_connection()
        try:
            with conn3.cursor() as cursor:

                if decision == "level_up" and current_level < 5:
                    new_level = current_level + 1

                    # Increment level in skill_levels
                    cursor.execute(
                        """
                        UPDATE skill_levels SET current_level = %s
                        WHERE user_id = %s AND career = %s
                        """,
                        (new_level, g.user_id, dream)
                    )

                    # Unlock the first locked skill of the new level
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

                # Save knowledge gaps into progress_log notes so
                # generate_roadmap() can read them on next call
                notes_str = ""
                if knowledge_gaps:
                    notes_str = "gaps:" + ",".join(knowledge_gaps)

                # Write progress_log row
                cursor.execute(
                    """
                    INSERT INTO progress_log
                        (user_id, attempt_number, total_score, previous_score,
                         level, status, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        g.user_id,
                        attempt_number,
                        total_score_percent,
                        previous_score,
                        current_level,
                        log_status,
                        notes_str,
                    )
                )

                # If level_up or ease_roadmap: regenerate roadmap
                if decision in ("level_up", "ease_roadmap"):
                    cursor.execute(
                        """
                        SELECT level, category, skill_name, sequence_order, status
                        FROM skill_tree
                        WHERE user_id = %s AND career = %s AND level <= %s
                        ORDER BY level ASC, sequence_order ASC
                        """,
                        (g.user_id, dream, new_level)
                    )
                    skill_tree = cursor.fetchall()

                    cursor.execute(
                        "SELECT subject, grade, gpa FROM academic_results WHERE user_id = %s",
                        (g.user_id,)
                    )
                    academics = cursor.fetchall()

                    cursor.execute(
                        """
                        SELECT MAX(version) AS max_v FROM roadmaps WHERE user_id = %s
                        """,
                        (g.user_id,)
                    )
                    ver_row      = cursor.fetchone()
                    next_version = (ver_row["max_v"] or 0) + 1

                    scores_ctx = [{"attempt": attempt_number,
                                   "total_score_percent": total_score_percent,
                                   "level": current_level}]

                    try:
                        rm = generate_roadmap(
                            dream, academics, skill_tree, scores_ctx, knowledge_gaps
                        )
                        stored_payload = json.dumps({
                            "overview":      rm.get("overview", ""),
                            "current_skill": rm.get("current_skill"),
                        })
                        cursor.execute(
                            "INSERT INTO roadmaps (user_id, roadmap_text, version) VALUES (%s, %s, %s)",
                            (g.user_id, stored_payload, next_version)
                        )
                    except Exception as e:
                        # Roadmap regeneration failing shouldn't block the
                        # level-up from being recorded — log and continue.
                        print(f"[progress/evaluate] roadmap regen error: {e}")

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
        print(f"[progress/evaluate] error: {e}")
        return jsonify({"error": "Progress evaluation failed unexpectedly"}), 500

    finally:
        conn.close()


# ============================================================
# GET /api/progress/log
# ============================================================
@progress_bp.route("/progress/log", methods=["GET"])
@token_required
def get_progress_log():
    """
    Return the full progress history for the student.

    Used by the Progress page to:
      - Draw the score-over-time graph (attempt_number on x-axis,
        total_score on y-axis) via Recharts/Chart.js
      - Show the current level badge
      - List all learned skills

    On success (200):
        {
          "current_level": 3,
          "progress_log": [
            {
              "attempt_number": 1,
              "total_score": 55.0,
              "previous_score": null,
              "level": 1,
              "status": "retained",
              "created_at": "2026-06-01T10:00:00"
            },
            ...
          ],
          "learned_skills": [
            {
              "skill_id": 5,
              "skill_name": "Variables",
              "category": "Programming Basics",
              "level": 1,
              "learned_at": "2026-06-02T14:00:00"
            },
            ...
          ]
        }
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

            # Current level
            cursor.execute(
                """
                SELECT sp.dream_career, sl.current_level
                FROM student_profiles sp
                JOIN skill_levels sl ON sl.user_id = sp.user_id AND sl.career = sp.dream_career
                WHERE sp.user_id = %s
                """,
                (g.user_id,)
            )
            level_info    = cursor.fetchone()
            current_level = level_info["current_level"] if level_info else 1

            # Full progress log oldest-first for the graph
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

            # All learned skills with skill tree details
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