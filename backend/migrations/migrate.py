"""
Lightweight, dependency-free migration runner.

Each file in this directory named NNNN_description.sql is applied exactly once,
in numeric order, and recorded in schema_migrations. This gives a reviewable,
versioned migration history without requiring a heavier framework.

Run directly:  python migrations/migrate.py
Also called automatically on backend startup (app/main.py).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent


def run_migrations(db_path: Path) -> list[str]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    applied: list[str] = []
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "id INTEGER PRIMARY KEY, filename TEXT UNIQUE NOT NULL, applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.commit()

        already = {row[0] for row in conn.execute("SELECT filename FROM schema_migrations")}

        for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if sql_file.name in already:
                continue
            script = sql_file.read_text(encoding="utf-8")
            conn.executescript(script)
            conn.execute("INSERT INTO schema_migrations (filename) VALUES (?)", (sql_file.name,))
            conn.commit()
            applied.append(sql_file.name)
    finally:
        conn.close()
    return applied


if __name__ == "__main__":
    from app.config import get_settings  # noqa: E402

    settings = get_settings()
    result = run_migrations(settings.database_path)
    if result:
        print(f"Applied migrations: {result}")
    else:
        print("Database already up to date.")
