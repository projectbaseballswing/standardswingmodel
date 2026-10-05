import io
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api import database
from api.database import Swing, User
from api.jobs import Job
from api.main import app
from api.storage import StorageError
from tests.video_fixture import VIDEO_BYTES


def upload(client, **form):
    return client.post("/api/analyses", data={"handedness": "right", **form},
                       files={"video": ("swing.mp4", VIDEO_BYTES, "video/mp4")})


def test_user_video_and_report_survive_new_process(mock_settings, fake_storage):
    user_id = uuid.uuid4().hex
    email = f"{user_id}@example.com"
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 200
        spec = client.get("/openapi.json").json()
        assert "/api/analyses/{analysis_id}/video" in spec["paths"]
        registered = client.post("/api/register", json={
            "id": user_id, "password": "test-password", "email": email, "nickname": user_id,
        })
        assert registered.json()["registered"] is True
        created = upload(client, user_id=user_id, recorded_at="2026-10-03T10:00:00+09:00")
        assert created.status_code == 202, created.text
        analysis_id = created.json()["analysis_id"]
        report = client.get(f"/api/analyses/{analysis_id}?include_series=true").json()
        assert report["user_id"] == user_id
        assert report["recorded_at"].startswith("2026-10-03T01:00:00")
        assert report["status"] == "done"
        assert report["result"]["speed"]["available"] is False
        assert all(item["user"] is None for item in report["result"]["speed"]["metrics"])
        first = client.get(f"/api/analyses/{analysis_id}/video").json()
        second = client.get(f"/api/analyses/{analysis_id}/video").json()
        assert first["url"] != second["url"]

    with database.SessionLocal() as db:
        user = db.get(User, user_id)
        row = db.get(Swing, analysis_id)
        assert user.password_hash != "test-password"
        assert user.created_at is not None
        assert row.user_id == user_id
        assert row.video_size_bytes == len(VIDEO_BYTES)
        assert fake_storage.objects[row.video_storage_path] == VIDEO_BYTES
        assert row.result["overall"]["score"] == report["result"]["overall"]["score"]
        assert row.result["joints"][0]["series"] is not None
        assert "https://" not in json.dumps(row.input)
        assert "https://" not in row.video_storage_path

    # A fresh interpreter has none of the original app's memory or SQLAlchemy pool.
    code = """
import sys
from fastapi.testclient import TestClient
from api.main import app
with TestClient(app) as client:
    login = client.post('/api/login', json={'id': sys.argv[1], 'password': 'test-password'})
    assert login.status_code == 200, login.text
    assert client.post('/api/me', json={'user': login.json()['user']}).status_code == 200
    analysis = client.get('/api/analyses/' + sys.argv[2]).json()
    assert analysis['status'] == 'done'
    assert analysis['result']['overall']['score'] is not None
print('persisted')
"""
    completed = subprocess.run([sys.executable, "-c", code, user_id, analysis_id],
                               env={**os.environ, "SWING_MOCK": "1"}, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert "persisted" in completed.stdout
    with TestClient(app) as client:
        assert client.get(f"/api/analyses/{analysis_id}/video").status_code == 200


def test_storage_failure_is_tracked_and_temp_file_removed(mock_client, fake_storage, monkeypatch):
    temporary = []

    def fail_upload(path, local_path, content_type):
        temporary.append(local_path)
        # Emulate a timeout after the remote server already received the object.
        fake_storage.objects[path] = Path(local_path).read_bytes()
        raise StorageError("test transfer interrupted")

    monkeypatch.setattr(fake_storage, "upload", fail_upload)
    response = upload(mock_client)
    assert response.status_code == 502
    analysis_id = response.json()["detail"]["analysis_id"]
    body = mock_client.get(f"/api/analyses/{analysis_id}").json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "STORAGE_UPLOAD_FAILED"
    assert body["result"] is None
    assert mock_client.get(f"/api/analyses/{analysis_id}/overall").status_code == 422
    with database.SessionLocal() as db:
        row = db.get(Swing, analysis_id)
        assert row.video_storage_path in fake_storage.objects
    assert all(not Path(path).exists() for path in temporary)


def test_upload_validation_has_no_db_or_storage_side_effects(mock_client, fake_storage, monkeypatch):
    import api.analyses
    monkeypatch.setattr(api.analyses, "settings", replace(api.analyses.settings, max_upload_mb=1))
    with database.SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(Swing))
    assert upload(mock_client, user_id="missing-user").status_code == 404
    assert upload(mock_client, recorded_at="2026-10-03T10:00:00").status_code == 422
    for filename, body, expected in [("file.txt", b"test", 415), ("swing.mp4", b"", 422),
                                     ("swing.mp4", b"x" * (1024 * 1024 + 1), 413)]:
        result = mock_client.post("/api/analyses", data={"handedness": "right"},
                                  files={"video": (filename, body, "video/mp4")})
        assert result.status_code == expected
    with database.SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Swing)) == before
    assert fake_storage.objects == {}


def test_restart_only_marks_own_unfinished_jobs(mock_settings, fake_storage):
    own_id, other_id = uuid.uuid4().hex, uuid.uuid4().hex
    with TestClient(app):
        app.state.jobs._add(Job(analysis_id=own_id, input={}, status="processing"))
    with database.SessionLocal.begin() as db:
        db.add(Swing(analysis_id=other_id, input={}, worker_id="another-pc", status="processing"))
    with TestClient(app) as client:
        own = client.get(f"/api/analyses/{own_id}").json()
        assert own["status"] == "failed"
        assert own["error"]["code"] == "SERVER_RESTARTED"
        assert client.get(f"/api/analyses/{other_id}").json()["status"] == "processing"


def test_nonmock_video_uses_existing_comparison_and_records_failures(fake_storage, monkeypatch):
    from feedback.pipeline import PipelineError, PipelineResult
    import api.analyses

    class Pipeline:
        def run(self, path, is_left, on_stage):
            on_stage("building_features")
            if is_left:
                raise PipelineError("INVALID_VIDEO", "test invalid video")
            store = app.state.store
            return PipelineResult(store.to_raw(store.template.mean), 30.0)

    monkeypatch.setattr(api.analyses, "SwingPipeline", lambda *args, **kwargs: Pipeline())
    monkeypatch.setattr(api.analyses, "settings", replace(api.analyses.settings, mock=False))
    with TestClient(app) as client:
        for handedness, expected in [("right", "done"), ("left", "failed")]:
            created = upload(client, handedness=handedness)
            assert created.status_code == 202
            analysis_id = created.json()["analysis_id"]
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                body = client.get(f"/api/analyses/{analysis_id}").json()
                if body["status"] in ("done", "failed"):
                    break
                time.sleep(0.02)
            assert body["status"] == expected
            with database.SessionLocal() as db:
                row = db.get(Swing, analysis_id)
                assert row.status == expected
                assert row.video_storage_path in fake_storage.objects
            if expected == "done":
                assert body["result"]["overall"]["score"] == 100.0
            else:
                assert body["error"]["code"] == "INVALID_VIDEO"


def test_feature_upload_in_mock_mode_is_persisted(mock_client):
    stream = io.BytesIO()
    np.save(stream, np.zeros((80, 64)))
    response = mock_client.post("/api/analyses/features", files={"features": ("swing.npy", stream.getvalue())})
    assert response.status_code == 200
    body = response.json()
    with database.SessionLocal() as db:
        row = db.get(Swing, body["analysis_id"])
        assert row.status == "done" and row.input["mock"] is True
    assert mock_client.get(f"/api/analyses/{body['analysis_id']}/video").status_code == 404


def test_database_insert_failure_prevents_storage_upload(mock_client, fake_storage, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def fail_insert(job):
        raise OperationalError("test statement", {}, Exception("test database unavailable"))

    monkeypatch.setattr(app.state.jobs, "_add", fail_insert)
    response = upload(mock_client)
    assert response.status_code == 503
    assert fake_storage.objects == {}
    assert "test statement" not in response.text


def test_database_failure_after_upload_remains_traceable(mock_client, fake_storage, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def fail_update(job):
        raise OperationalError("test statement", {}, Exception("test database unavailable"))

    monkeypatch.setattr(app.state.jobs, "_save", fail_update)
    response = upload(mock_client)
    assert response.status_code == 503
    assert len(fake_storage.objects) == 1
    path = next(iter(fake_storage.objects))
    with database.SessionLocal() as db:
        row = db.scalar(select(Swing).where(Swing.video_storage_path == path))
        assert row is not None
        assert row.status == "queued" and row.stage == "uploading"
    app.state.jobs.recover_interrupted()
    with database.SessionLocal() as db:
        row = db.scalar(select(Swing).where(Swing.video_storage_path == path))
        assert row.status == "failed"
        assert row.error["code"] == "SERVER_RESTARTED"


def test_video_job_lifecycle_is_persisted(fake_storage, monkeypatch):
    import threading
    import api.analyses
    from feedback.pipeline import PipelineResult

    started, release = threading.Event(), threading.Event()
    original_upload = fake_storage.upload
    def check_upload(path, local_path, content_type):
        with database.SessionLocal() as db:
            row = db.scalar(select(Swing).where(Swing.video_storage_path == path))
            assert row.status == "queued" and row.stage == "uploading" and row.result is None
        original_upload(path, local_path, content_type)
    monkeypatch.setattr(fake_storage, "upload", check_upload)
    class Pipeline:
        def run(self, path, is_left, on_stage):
            on_stage("reading_video")
            started.set()
            assert release.wait(10)
            store = app.state.store
            return PipelineResult(store.to_raw(store.template.mean), 30.0)
    monkeypatch.setattr(api.analyses, "SwingPipeline", lambda *args, **kwargs: Pipeline())
    monkeypatch.setattr(api.analyses, "settings", replace(api.analyses.settings, mock=False))
    with TestClient(app) as client:
        try:
            response = upload(client)
            assert response.status_code == 202 and response.json()["status"] == "queued"
            analysis_id = response.json()["analysis_id"]
            assert started.wait(10)
            state = client.get(f"/api/analyses/{analysis_id}").json()
            assert state["status"] == "processing" and state["stage"] == "reading_video"
            assert client.get(f"/api/analyses/{analysis_id}/overall").status_code == 409
        finally:
            release.set()
    with database.SessionLocal() as db:
        row = db.get(Swing, analysis_id)
        assert row.status == "done" and row.finished_at is not None and row.stage is None
