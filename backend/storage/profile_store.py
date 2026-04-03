from adapters.database_adapter import execute, fetchone


def upsert_profile(user_id: str, email: str) -> dict:
    existing = fetchone("SELECT * FROM profiles WHERE id = ?", (user_id,))
    if existing:
        execute(
            "UPDATE profiles SET email = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (email, user_id),
        )
    else:
        execute(
            "INSERT INTO profiles (id, email) VALUES (?, ?)",
            (user_id, email),
        )
    return fetchone("SELECT * FROM profiles WHERE id = ?", (user_id,)) or {"id": user_id, "email": email}
