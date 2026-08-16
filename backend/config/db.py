"""
config/db.py
-------------
PostgreSQL connection via psycopg2 (Supabase).
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor


def get_db_connection():
    conn = psycopg2.connect(
        os.getenv("DATABASE_URL"),
        cursor_factory=RealDictCursor,
    )
    conn.autocommit = True
    return conn


def test_connection():
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
        return True
    except Exception as e:
        print(f"[db] connection test failed: {e}")
        return False