"""
services/fifo_service.py
-------------------------
FIFO (First-In-First-Out) cleanup logic for quiz sessions.

Per Section 10 of the design doc:
  - Level-up tests:  keep the LAST 2 sessions' questions + answers only.
                     Scores, levels, and progress logs are NEVER deleted.
  - Skill tests:     keep the LAST session's questions + answers only
                     (latest-attempt-only FIFO).
  - Placement test:  never cleaned up (one-time, permanent).

These functions are called from quiz.py BEFORE a new session is created,
so the old data is removed first and the new session is the "latest".

They are plain functions (not background jobs / cron tasks) so they are
easy to call inline, easy to test with dummy data, and easy to demo.
"""

from config.db import get_db_connection


def cleanup_level_up_sessions(conn, user_id):
    """
    Keep only the 2 most recent level_up quiz sessions for this user.
    Deletes quiz_questions and quiz_answers for older sessions via
    CASCADE (schema has ON DELETE CASCADE on both tables).

    quiz_scores and progress_log rows are on separate tables that do NOT
    cascade from quiz_sessions, so scores/progress are preserved.

    Args:
        conn:    active PyMySQL connection (passed in from the route so
                  we reuse the same connection, no extra open/close)
        user_id: int
    """
    with conn.cursor() as cursor:
        # Find all level_up session ids for this user, newest first
        cursor.execute(
            """
            SELECT id FROM quiz_sessions
            WHERE user_id = %s AND test_type = 'level_up'
            ORDER BY created_at DESC, id DESC
            """,
            (user_id,)
        )
        rows = cursor.fetchall()

    # Keep the 2 newest; delete anything older (indices 2+)
    sessions_to_delete = [row["id"] for row in rows[2:]]

    if sessions_to_delete:
        _delete_sessions(conn, sessions_to_delete)


def cleanup_skill_test_session(conn, user_id, skill_id):
    """
    Delete the previous skill_test session (questions + answers) for
    this specific skill so only the latest attempt is kept.

    Args:
        conn:     active PyMySQL connection
        user_id:  int
        skill_id: int - the skill_tree.id being tested
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id FROM quiz_sessions
            WHERE user_id = %s AND test_type = 'skill_test' AND skill_id = %s
            ORDER BY created_at DESC, id DESC
            """,
            (user_id, skill_id)
        )
        rows = cursor.fetchall()

    # Delete ALL previous sessions for this skill (we're about to create
    # a fresh one, so everything before it is stale).
    sessions_to_delete = [row["id"] for row in rows]

    if sessions_to_delete:
        _delete_sessions(conn, sessions_to_delete)


def _delete_sessions(conn, session_ids):
    """
    Delete quiz_sessions by id list.
    quiz_questions and quiz_answers are removed automatically via the
    ON DELETE CASCADE foreign keys defined in schema.sql.

    Args:
        conn:        active PyMySQL connection
        session_ids: list of int
    """
    if not session_ids:
        return

    placeholders = ", ".join(["%s"] * len(session_ids))
    with conn.cursor() as cursor:
        cursor.execute(
            f"DELETE FROM quiz_sessions WHERE id IN ({placeholders})",
            session_ids
        )