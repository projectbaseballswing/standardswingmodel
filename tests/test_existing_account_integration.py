"""Existing account/history compatibility, using disposable SQLite only."""

import uuid

from fastapi.testclient import TestClient

from api import database
from api.database import Swing, User
from api.main import app
from api.security import hash_password
from tests.video_fixture import VIDEO_BYTES


def test_preexisting_bcrypt_account_logs_in_without_copy_or_password_change(mock_settings, fake_storage):
    uid = "existing-" + uuid.uuid4().hex
    password = "synthetic-fixture-password"
    original_hash = hash_password(password)
    owned, ownerless = uuid.uuid4().hex, uuid.uuid4().hex
    with database.SessionLocal.begin() as db:
        db.add(User(user_id=uid, email=uid + "@example.com", nickname=uid,
                    password_hash=original_hash))
        db.flush()
        db.add_all([
            Swing(analysis_id=owned, user_id=uid, worker_id="historic", status="done", input={}, result={}),
            Swing(analysis_id=ownerless, user_id=None, worker_id="historic", status="done", input={}, result={}),
        ])
    with TestClient(app) as client:
        response = client.post("/api/login", json={"id": uid, "password": password})
        assert response.status_code == 200
        assert response.json()["user"] == uid
        client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        assert client.get(f"/api/analyses/{owned}/pose-3d").status_code == 404
        assert client.get(f"/api/analyses/{ownerless}/pose-3d").status_code == 403
        assert client.post("/api/me", json={"user": uid}).json()["id"] == uid
    with database.SessionLocal() as db:
        assert db.get(User, uid).password_hash == original_hash
        assert db.get(Swing, owned).user_id == uid
        assert db.get(Swing, ownerless).user_id is None


def test_pose_initialization_failure_preserves_existing_score_workflow(mock_client, monkeypatch):
    import api.pose3d

    def fail_initialization(job):
        raise RuntimeError("synthetic optional-display failure")

    monkeypatch.setattr(api.pose3d, "init_pose", fail_initialization)
    response = mock_client.post(
        "/api/analyses", data={"handedness": "right"},
        files={"video": ("fixture.mp4", VIDEO_BYTES, "video/mp4")},
    )
    assert response.status_code == 202
    analysis_id = response.json()["analysis_id"]
    score = mock_client.get(f"/api/analyses/{analysis_id}").json()
    assert score["status"] == "done" and score["result"]["overall"]
    assert mock_client.get(f"/api/analyses/{analysis_id}/pose-3d").status_code == 404
