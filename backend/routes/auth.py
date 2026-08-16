"""
routes/auth.py
----------------
Authentication routes:
    POST /api/auth/register   - create account (bcrypt hash)
    POST /api/auth/login      - verify credentials, issue JWT

These are the only two routes in the whole app that do NOT require
@token_required - everything else needs a valid JWT (see utils/auth.py).
"""

import bcrypt
from flask import Blueprint, request, jsonify

from config.db import get_db_connection
from utils.auth import generate_token

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["POST"])
def register():
    """
    Create a new user account.

    Expected JSON body:
        {
          "name": "Alice",
          "email": "alice@example.com",
          "password": "plaintext-password"
        }

    Validation:
        - name, email, password are all required and non-empty
          (per Section 12: "every route validates required fields exist
          before hitting the DB")
        - email must not already be registered (unique constraint in
          schema.sql backs this up at the DB level too)

    On success (201):
        { "message": "Account created successfully" }

    On failure:
        400 - missing/empty fields
        409 - email already registered
        500 - unexpected server error
    """
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not name or not email or not password:
        return jsonify({"error": "name, email and password are all required"}), 400

    # Hash the password - bcrypt generates its own per-password salt
    # automatically, so we don't need to store a separate salt column.
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Check for an existing account with this email first, so we
            # can return a clean 409 instead of a raw DB integrity error.
            cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            if cursor.fetchone():
                return jsonify({"error": "An account with this email already exists"}), 409

            cursor.execute(
                "INSERT INTO users (name, email, password) VALUES (%s, %s, %s)",
                (name, email, password_hash.decode("utf-8")),
            )

        return jsonify({"message": "Account created successfully"}), 201

    except Exception as e:
        print(f"[auth/register] error: {e}")
        return jsonify({"error": "Could not create account"}), 500

    finally:
        conn.close()


@auth_bp.route("/login", methods=["POST"])
def login():
    """
    Verify credentials and issue a JWT.

    Expected JSON body:
        {
          "email": "alice@example.com",
          "password": "plaintext-password"
        }

    On success (200):
        {
          "token": "<jwt>",
          "user": { "id": 1, "name": "Alice", "email": "alice@example.com" }
        }

    On failure:
        400 - missing/empty fields
        401 - email not found OR password does not match
              (deliberately the SAME error message for both cases, so we
              don't reveal whether an email is registered)
        500 - unexpected server error
    """
    data = request.get_json(silent=True) or {}

    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, email, password FROM users WHERE email = %s",
                (email,),
            )
            user = cursor.fetchone()

        if not user:
            return jsonify({"error": "Invalid email or password"}), 401

        stored_hash = user["password"].encode("utf-8")
        if not bcrypt.checkpw(password.encode("utf-8"), stored_hash):
            return jsonify({"error": "Invalid email or password"}), 401

        token = generate_token(user["id"])

        return jsonify({
            "token": token,
            "user": {
                "id": user["id"],
                "name": user["name"],
                "email": user["email"],
            },
        }), 200

    except Exception as e:
        print(f"[auth/login] error: {e}")
        return jsonify({"error": "Login failed"}), 500

    finally:
        conn.close()