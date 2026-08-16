"""
utils/auth.py
--------------
Shared JWT helpers used across the whole backend.

Per Section 12 of the design doc, every protected route is wrapped with
a SINGLE @token_required decorator that:
  - reads the "Authorization: Bearer <token>" header
  - verifies the JWT signature/expiry
  - attaches the user_id to the request (via flask.g) so the route
    handler can use it without re-decoding the token itself.

This file is intentionally the ONLY place that creates or verifies JWTs,
so the secret/algorithm/expiry logic lives in one place.
"""

import os
import jwt
from functools import wraps
from datetime import datetime, timedelta, timezone
from flask import request, jsonify, g


def _get_jwt_secret():
    """Read the JWT secret from the environment (set in .env)."""
    secret = os.getenv("JWT_SECRET")
    if not secret:
        # Fail loudly in development if the secret was never configured -
        # better than silently issuing tokens with a default/blank secret.
        raise RuntimeError("JWT_SECRET is not set. Check your .env file.")
    return secret


def generate_token(user_id):
    """
    Create a signed JWT for the given user_id.

    The token payload contains:
      - "user_id": used by token_required to identify the requester
      - "exp":     expiry timestamp, controlled by JWT_EXPIRES_HOURS
                    in .env (defaults to 24 hours)

    Returns the encoded JWT as a string.
    """
    expires_hours = int(os.getenv("JWT_EXPIRES_HOURS", "24"))
    payload = {
        "user_id": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=expires_hours),
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")
    return token


def token_required(f):
    """
    Decorator for protected routes.

    Usage:
        @auth_bp.route("/some-route")
        @token_required
        def some_route():
            user_id = g.user_id
            ...

    Behaviour:
      - Missing/malformed Authorization header -> 401
      - Expired token                          -> 401
      - Invalid signature / tampered token     -> 401
      - Valid token                            -> attaches g.user_id and
                                                    calls the wrapped route
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or malformed Authorization header"}), 401

        token = auth_header.split(" ", 1)[1].strip()

        try:
            payload = jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401

        # Attach user_id to Flask's per-request context "g" object so
        # any route can read it via `from flask import g; g.user_id`
        g.user_id = payload["user_id"]

        return f(*args, **kwargs)

    return decorated