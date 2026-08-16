"""
routes/profile.py
-------------------
Handles:
    POST /api/profile/dream     - save dream career + passion statement
    POST /api/academics/manual  - save manually-entered academic rows
    GET  /api/academics         - fetch all academic results for the student

All routes here require a valid JWT (@token_required), which attaches
g.user_id - every query is scoped to that user_id so students can only
ever see/modify their own data.
"""

from flask import Blueprint, request, jsonify, g

from config.db import get_db_connection
from utils.auth import token_required

profile_bp = Blueprint("profile", __name__)


# ============================================================
# POST /api/profile/dream
# ============================================================
@profile_bp.route("/profile/dream", methods=["POST"])
@token_required
def save_dream():
    """
    Save (or update) the student's dream career + passion statement.

    Expected JSON body:
        {
          "dream_career": "Software Developer",
          "passion_statement": "I love building things that solve real problems."
        }

    Validation:
        - dream_career is required and non-empty.
        - passion_statement is optional (defaults to empty string).

    Behaviour:
        - One profile row per user. If a profile already exists for
          g.user_id, it is UPDATED in place (e.g. the student changes
          their mind about their dream career later). Otherwise a new
          row is INSERTED.

    On success (200):
        { "message": "Profile saved successfully" }
    """
    data = request.get_json(silent=True) or {}

    dream_career = (data.get("dream_career") or "").strip()
    passion_statement = (data.get("passion_statement") or "").strip()

    if not dream_career:
        return jsonify({"error": "dream_career is required"}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM student_profiles WHERE user_id = %s",
                (g.user_id,),
            )
            existing = cursor.fetchone()

            if existing:
                cursor.execute(
                    """
                    UPDATE student_profiles
                    SET dream_career = %s, passion_statement = %s
                    WHERE user_id = %s
                    """,
                    (dream_career, passion_statement, g.user_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO student_profiles (user_id, dream_career, passion_statement)
                    VALUES (%s, %s, %s)
                    """,
                    (g.user_id, dream_career, passion_statement),
                )

        return jsonify({"message": "Profile saved successfully"}), 200

    except Exception as e:
        print(f"[profile/dream] error: {e}")
        return jsonify({"error": "Could not save profile"}), 500

    finally:
        conn.close()


# ============================================================
# POST /api/academics/manual
# ============================================================
@profile_bp.route("/academics/manual", methods=["POST"])
@token_required
def save_academics_manual():
    """
    Save manually-entered academic result rows.

    Expected JSON body:
        {
          "rows": [
            {"subject": "Math", "grade": "A", "gpa": 3.8},
            {"subject": "Physics", "grade": "B+", "gpa": 3.5}
          ]
        }

    Validation:
        - "rows" must be a non-empty list.
        - Each row must have a non-empty "subject".
        - "grade" is optional (defaults to null).
        - "gpa" is optional and must be a number if provided (defaults to null).

    Behaviour (per Section 4, step 3c / Section 10):
        - Rows are APPENDED to academic_results with source='manual'.
        - This endpoint never deletes or overwrites previous rows -
          students can submit academic data multiple times over the
          years, and every upload just adds more rows for the AI to
          consider later.

    On success (201):
        { "message": "Saved 2 academic record(s)" }
    """
    data = request.get_json(silent=True) or {}
    rows = data.get("rows")

    if not isinstance(rows, list) or len(rows) == 0:
        return jsonify({"error": "rows must be a non-empty list"}), 400

    # Validate every row up front before touching the DB, so a bad row
    # later in the list doesn't leave a partial save behind.
    cleaned_rows = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            return jsonify({"error": f"rows[{i}] must be an object"}), 400

        subject = (row.get("subject") or "").strip()
        if not subject:
            return jsonify({"error": f"rows[{i}].subject is required"}), 400

        grade = row.get("grade")
        grade = str(grade).strip() if grade is not None else None

        gpa = row.get("gpa")
        if gpa is not None:
            try:
                gpa = float(gpa)
            except (TypeError, ValueError):
                return jsonify({"error": f"rows[{i}].gpa must be a number"}), 400

        cleaned_rows.append((g.user_id, subject, grade, gpa, "manual"))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO academic_results (user_id, subject, grade, gpa, source)
                VALUES (%s, %s, %s, %s, %s)
                """,
                cleaned_rows,
            )

        return jsonify({"message": f"Saved {len(cleaned_rows)} academic record(s)"}), 201

    except Exception as e:
        print(f"[academics/manual] error: {e}")
        return jsonify({"error": "Could not save academic results"}), 500

    finally:
        conn.close()


# ============================================================
# GET /api/academics
# ============================================================
@profile_bp.route("/academics", methods=["GET"])
@token_required
def get_academics():
    """
    Fetch ALL academic results for the logged-in student, across every
    upload (manual entries + OCR uploads), oldest first.

    On success (200):
        {
          "academics": [
            {
              "id": 1,
              "subject": "Math",
              "grade": "A",
              "gpa": 3.8,
              "source": "manual",
              "uploaded_at": "2026-06-13T10:00:00"
            },
            ...
          ]
        }
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, subject, grade, gpa, source, uploaded_at
                FROM academic_results
                WHERE user_id = %s
                ORDER BY uploaded_at ASC, id ASC
                """,
                (g.user_id,),
            )
            rows = cursor.fetchall()

        # Convert datetime objects to ISO strings so jsonify() doesn't
        # choke on them.
        for row in rows:
            if row.get("uploaded_at") is not None:
                row["uploaded_at"] = row["uploaded_at"].isoformat()

        return jsonify({"academics": rows}), 200

    except Exception as e:
        print(f"[academics/get] error: {e}")
        return jsonify({"error": "Could not fetch academic results"}), 500

    finally:
        conn.close()