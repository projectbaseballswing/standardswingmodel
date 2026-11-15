import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError


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
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0004"
        columns = {row[1] for row in db.execute("PRAGMA table_info(swings)")}
        assert {"user_id", "video_storage_path", "result", "worker_id", "video_delete_requested_at", "video_deleted_at"} <= columns


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
    assert "ADD COLUMN video_delete_requested_at" in sql
    assert "ADD COLUMN video_deleted_at" in sql


def test_video_delete_migration_preserves_existing_analysis(tmp_path):
    path = tmp_path / "before-delete-feature.db"
    url = "sqlite:///" + str(path)
    alembic(url, "upgrade", "0003")
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO swings (analysis_id, worker_id, status, input, result, video_storage_path, created_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?)",
                   ('old-analysis', 'migration-test', 'done', '{}', '{"overall":{"score":77.3}}', 'swings/old-analysis/original.mp4', '2026-11-11 00:00:00'))
    alembic(url, "upgrade", "head")
    with sqlite3.connect(path) as db:
        row = db.execute("SELECT result, video_storage_path, video_delete_requested_at, video_deleted_at FROM swings").fetchone()
        assert row == ('{"overall":{"score":77.3}}', 'swings/old-analysis/original.mp4', None, None)
    alembic(url, "downgrade", "0003")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT result, video_storage_path FROM swings").fetchone() == row[:2]


def test_video_delete_code_requires_0004_before_deployment(tmp_path):
    """A healthy process alone is not proof that a 0003 DB can serve swings."""
    from api.database import Swing

    url = "sqlite:///" + str(tmp_path / "unmigrated.db")
    alembic(url, "upgrade", "0003")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            with pytest.raises(OperationalError, match="video_delete_requested_at"):
                connection.execute(select(Swing).limit(1))
        alembic(url, "upgrade", "0004")
        with engine.connect() as connection:
            assert connection.execute(select(Swing).limit(1)).all() == []
    finally:
        engine.dispose()
