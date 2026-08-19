import re

from services.groq_service import generate_skill_tree


def _normalize_career(career):
    return re.sub(r"\s+", " ", career.strip().lower())


def get_or_create_core_tree(conn, dream):
    """
    Calls Groq only the first time a career appears.
    All later learners receive the stored core curriculum.
    """
    normalized = _normalize_career(dream)

    with conn.cursor() as cursor:
        # Prevent two first-time requests from creating different trees.
        cursor.execute(
            "SELECT pg_advisory_lock(hashtext(%s))",
            (normalized,),
        )

        try:
            cursor.execute(
                """
                INSERT INTO career_core_trees (career_name, normalized_career)
                VALUES (%s, %s)
                ON CONFLICT (normalized_career)
                DO UPDATE SET career_name = career_core_trees.career_name
                RETURNING id
                """,
                (dream.strip(), normalized),
            )
            tree_id = cursor.fetchone()["id"]

            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM career_core_skills
                WHERE core_tree_id = %s
                """,
                (tree_id,),
            )
            already_exists = cursor.fetchone()["count"] > 0

            if already_exists:
                return tree_id

            # Standardized tree: career only, no learner academics/scores.
            result = generate_skill_tree(dream, academics=[], placement_level=1)
            skills = result.get("skills", [])

            for skill in skills:
                cursor.execute(
                    """
                    INSERT INTO career_core_skills
                        (core_tree_id, level, category, skill_name,
                         sequence_order, skill_type)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (core_tree_id, level, sequence_order)
                    DO NOTHING
                    """,
                    (
                        tree_id,
                        skill["level"],
                        skill["category"],
                        skill["skill_name"],
                        skill["sequence_order"],
                        skill.get("skill_type", "mixed"),
                    ),
                )

            return tree_id

        finally:
            cursor.execute(
                "SELECT pg_advisory_unlock(hashtext(%s))",
                (normalized,),
            )


def assign_tree_to_learner(conn, user_id, dream, starting_level):
    """
    Copies the same stored core tree into the existing learner skill_tree.

    starting_level changes only learned/unlocked/locked status.
    It never changes the shared core skill list.
    """
    tree_id = get_or_create_core_tree(conn, dream)

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM skill_tree
            WHERE user_id = %s AND career = %s
            """,
            (user_id, dream),
        )
        if cursor.fetchone()["count"] > 0:
            return

        cursor.execute(
            """
            SELECT id, level, category, skill_name,
                   sequence_order, skill_type
            FROM career_core_skills
            WHERE core_tree_id = %s
            ORDER BY level, sequence_order
            """,
            (tree_id,),
        )
        core_skills = cursor.fetchall()

        rows = []

        for core in core_skills:
            if core["level"] < starting_level:
                status = "learned"
            elif (
                core["level"] == starting_level
                and core["sequence_order"] == 1
            ):
                status = "unlocked"
            else:
                status = "locked"

            rows.append(
                (
                    user_id,
                    dream,
                    core["level"],
                    core["category"],
                    core["skill_name"],
                    core["sequence_order"],
                    status,
                    core["skill_type"],
                    "core",
                    core["id"],
                )
            )

        cursor.executemany(
            """
            INSERT INTO skill_tree
                (user_id, career, level, category, skill_name,
                 sequence_order, status, skill_type, skill_category,
                 core_skill_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            rows,
        )

        # Preserve your existing learned_skills behavior.
        cursor.execute(
            """
            SELECT id
            FROM skill_tree
            WHERE user_id = %s
              AND career = %s
              AND status = 'learned'
            """,
            (user_id, dream),
        )

        learned_rows = [
            (user_id, row["id"])
            for row in cursor.fetchall()
        ]

        if learned_rows:
            cursor.executemany(
                """
                INSERT INTO learned_skills (user_id, skill_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, skill_id) DO NOTHING
                """,
                learned_rows,
            )