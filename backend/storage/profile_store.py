from adapters.database_adapter import _adapt_query, _connect, fetchone


def get_profile_by_email(email: str) -> dict | None:
    return fetchone("SELECT * FROM profiles WHERE email = ?", (email,))


def upsert_profile(user_id: str, email: str) -> dict:
    with _connect() as conn:
        conn.execute(
            _adapt_query(
                """
                INSERT INTO profiles (id, email)
                VALUES (?, ?)
                ON CONFLICT(id) DO UPDATE
                SET email = excluded.email,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            (user_id, email),
        )
        row = conn.execute(
            _adapt_query("SELECT * FROM profiles WHERE id = ?"),
            (user_id,),
        ).fetchone()
        return dict(row) if row else {"id": user_id, "email": email}
