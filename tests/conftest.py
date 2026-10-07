"""All tests use a disposable SQLite DB and an explicit in-process storage fake."""

import atexit
import os
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from dotenv import dotenv_values

# Used only by the opt-in subprocess. Unit tests never use these connections.
_supabase_environment = {**dotenv_values(Path(__file__).resolve().parents[1] / ".env"), **os.environ}


def integration_environment():
    keys = ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_STORAGE_BUCKET")
    return {key: _supabase_environment.get(key) or "" for key in keys}

# Set before importing api.main/database. Never connect tests to the team's DB.
_directory = TemporaryDirectory(prefix="swing-tests-")
atexit.register(_directory.cleanup)
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(_directory.name) / "test.db")
os.environ["SWING_MOCK"] = "0"
os.environ["SWING_WORKER_ID"] = "test-worker"
for _name in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_STORAGE_BUCKET"):
    os.environ[_name] = ""


class FakeStorage:
    bucket = "test-videos"
    expires_in = 60

    def __init__(self):
        self.objects = {}
        self.sign_count = 0

    def upload(self, path, local_path, content_type):
        self.objects[path] = Path(local_path).read_bytes()

    def signed_url(self, bucket, path):
        from api.storage import StorageError
        if bucket != self.bucket or path not in self.objects:
            raise StorageError("Test object does not exist")
        self.sign_count += 1
        return f"https://storage.invalid/{bucket}/{path}?test={self.sign_count}"

    def close(self):
        pass


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    from alembic import command
    from alembic.config import Config
    from api import database

    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    yield
    database.engine.dispose()


@pytest.fixture
def fake_storage(monkeypatch):
    import api.analyses
    storage = FakeStorage()
    monkeypatch.setattr(api.analyses, "create_storage", lambda: storage)
    return storage


@pytest.fixture
def mock_settings(monkeypatch):
    import api.analyses
    configured = replace(api.analyses.settings, mock=True)
    monkeypatch.setattr(api.analyses, "settings", configured)
    return configured


@pytest.fixture
def mock_client(mock_settings, fake_storage):
    from fastapi.testclient import TestClient
    from api.main import app
    with TestClient(app) as client:
        yield client
