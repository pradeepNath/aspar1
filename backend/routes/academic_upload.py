"""
routes/academic_upload.py
--------------------------
Handles the OCR upload path for academic results:

    POST /api/academics/upload
        - Accepts an image or PDF via multipart/form-data
        - Runs OCR to get raw text (ocr_service)
        - Sends raw text to Groq to get structured rows (groq_service)
        - Returns the structured rows to the frontend for student review
        - Does NOT save to the database yet - saving happens via a
          separate confirm step below.

    POST /api/academics/upload/confirm
        - Student has reviewed + optionally edited the AI-structured rows
        - Receives the confirmed rows and saves them to academic_results
          with source='ocr_upload'

Two-step design reason: OCR + AI can misread things. Showing the
extracted rows in an editable table before saving (Section 4, step 3b)
lets the student fix mistakes before they affect their AI analysis.
"""

import os
from flask import Blueprint, request, jsonify, g

from config.db import get_db_connection
from utils.auth import token_required
from services.ocr_service import extract_text_from_file
from services.groq_service import structure_ocr_text

academic_upload_bp = Blueprint("academic_upload", __name__)

# Maximum upload size: 10 MB. Enforced here in addition to any web
# server limits because we read the whole file into memory for OCR.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


# ============================================================
# POST /api/academics/upload
# Step 1: OCR → AI structuring → return rows for review
# ============================================================
@academic_upload_bp.route("/academics/upload", methods=["POST"])
@token_required
def upload_academic_file():
    """
    Accept a file upload, run OCR on it, then use AI to extract
    structured subject/grade/GPA rows. Returns the rows for review.

    Request: multipart/form-data with field "file"

    On success (200):
        {
          "rows": [
            {"subject": "Mathematics", "grade": "A",  "gpa": 3.8},
            {"subject": "Physics",     "grade": "B+", "gpa": 3.5}
          ],
          "raw_text_preview": "first 300 chars of OCR output (debug aid)"
        }

    On failure:
        400 - no file sent, empty file, or unsupported format
        422 - OCR succeeded but AI could not extract any rows
        500 - OCR engine error or AI error
    """
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded. Send a 'file' field in form-data"}), 400

    uploaded_file = request.files["file"]
    filename = uploaded_file.filename or ""

    if not filename:
        return jsonify({"error": "Uploaded file has no name"}), 400

    file_bytes = uploaded_file.read()

    if len(file_bytes) == 0:
        return jsonify({"error": "Uploaded file is empty"}), 400

    if len(file_bytes) > MAX_UPLOAD_BYTES:
        mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        return jsonify({"error": f"File exceeds maximum allowed size of {mb} MB"}), 400

    # --- Step 1: OCR ---
    try:
        raw_text = extract_text_from_file(file_bytes, filename)
    except ValueError as e:
        # Unsupported file format
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        # OCR engine failure
        print(f"[academic_upload] OCR error: {e}")
        return jsonify({"error": f"OCR failed: {e}"}), 500

    if not raw_text:
        return jsonify({"error": "OCR extracted no text from the file. "
                                  "Try a clearer scan or enter results manually."}), 422

    # --- Step 2: AI structuring ---
    try:
        rows = structure_ocr_text(raw_text)
    except Exception as e:
        print(f"[academic_upload] Groq structuring error: {e}")
        return jsonify({"error": "AI could not structure the OCR text. "
                                  "Try entering results manually."}), 500

    if not isinstance(rows, list) or len(rows) == 0:
        return jsonify({"error": "AI could not find any subjects in the document. "
                                  "Try a clearer scan or enter results manually."}), 422

    return jsonify({
        "rows": rows,
        # A short preview of the raw OCR text is handy in the console
        # during development - the frontend can ignore this field.
        "raw_text_preview": raw_text[:300],
    }), 200


# ============================================================
# POST /api/academics/upload/confirm
# Step 2: Student confirms (and possibly edits) the extracted rows
# ============================================================
@academic_upload_bp.route("/academics/upload/confirm", methods=["POST"])
@token_required
def confirm_academic_upload():
    """
    Save the student-reviewed OCR rows to academic_results.

    Expected JSON body:
        {
          "rows": [
            {"subject": "Mathematics", "grade": "A",  "gpa": 3.8},
            {"subject": "Physics",     "grade": "B+", "gpa": null}
          ]
        }

    These rows come straight back from the frontend after the student
    has reviewed and optionally edited the AI-extracted data.

    Validation: same rules as manual save (subject required, gpa numeric
    if provided). source is set to 'ocr_upload' instead of 'manual'.

    On success (201):
        { "message": "Saved 2 academic record(s)" }
    """
    data = request.get_json(silent=True) or {}
    rows = data.get("rows")

    if not isinstance(rows, list) or len(rows) == 0:
        return jsonify({"error": "rows must be a non-empty list"}), 400

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

        cleaned_rows.append((g.user_id, subject, grade, gpa, "ocr_upload"))

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
        print(f"[academic_upload/confirm] error: {e}")
        return jsonify({"error": "Could not save academic results"}), 500

    finally:
        conn.close()