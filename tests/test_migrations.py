import os
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def alembic(url, *args):
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT,
                            env={**os.environ, "DATABASE_URL": url},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_fresh_database_matches_models(tmp_path):
    path = tmp_path / "fresh.db"
    url = "sqlite:///" + str(path)
    alembic(url, "upgrade", "head")
    alembic(url, "check")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0002"
        columns = {row[1] for row in db.execute("PRAGMA table_info(swings)")}
        assert {"user_id", "video_storage_path", "result", "worker_id"} <= columns


def test_legacy_users_are_preserved(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE users (id VARCHAR PRIMARY KEY NOT NULL, email VARCHAR NOT NULL UNIQUE, "
                   "nickname VARCHAR NOT NULL UNIQUE, password_hash VARCHAR NOT NULL)")
        db.execute("INSERT INTO users VALUES (?, ?, ?, ?)", ("legacy", "legacy@example.com", "legacy", "old-hash"))
    url = "sqlite:///" + str(path)
    alembic(url, "stamp", "0001")
    alembic(url, "upgrade", "head")
    with sqlite3.connect(path) as db:
        row = db.execute("SELECT id, password_hash, created_at FROM users").fetchone()
        assert row[:2] == ("legacy", "old-hash")
        assert row[2] is not None


def test_postgres_migration_compiles_without_connection():
    # No credentials and no server: offline SQL generation only.
    sql = alembic("postgresql+psycopg://", "upgrade", "head", "--sql")
    assert "JSONB" in sql
    assert "FOREIGN KEY(user_id) REFERENCES users (id)" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
