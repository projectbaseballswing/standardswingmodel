"""피처(.npy) 업로드 경로로 API 전체 흐름을 확인한다. 영상/YOLO 없이 돌아간다.

    python -m pytest tests
"""

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def _npy_bytes(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, array)
    return buffer.getvalue()


def _template_like_features(noise: float = 0.0, extra_velocity: bool = False) -> np.ndarray:
    """기준 템플릿을 원래 단위로 되돌린 피처. noise 는 scaled 단위 표준편차."""
    store = app.state.store
    raw = store.to_raw(store.template.mean)
    rng = np.random.default_rng(0)
    raw = raw + rng.normal(0, noise, raw.shape) * store.scaler["std"]
    if extra_velocity:
        raw = np.concatenate([raw, np.zeros((raw.shape[0], 3))], axis=1)
    return raw


def _upload(client, features: np.ndarray, **form):
    return client.post(
        "/api/analyses/features",
        files={"features": ("swing.npy", _npy_bytes(features), "application/octet-stream")},
        data=form,
    )


def test_feature_analysis_and_sub_endpoints(client):
    response = _upload(client, _template_like_features(noise=0.1, extra_velocity=True))
    assert response.status_code == 200, response.text
    analysis = response.json()
    assert analysis["status"] == "done"
    analysis_id = analysis["analysis_id"]

    overall = client.get(f"/api/analyses/{analysis_id}/overall").json()
    assert 0 <= overall["score"] <= 100
    assert len(overall["frame_distances"]) == 80
    assert "similar_players" not in overall

    joints = client.get(f"/api/analyses/{analysis_id}/joints").json()["joints"]
    assert len(joints) == 7
    assert all(joint["series"] is None for joint in joints)
    assert [p["phase"] for p in joints[0]["phases"]] == ["stance", "load", "swing", "follow_through"]

    joints_with_series = client.get(f"/api/analyses/{analysis_id}/joints?include_series=true").json()["joints"]
    assert len(joints_with_series[0]["series"]["user"]) == 80

    phases = client.get(f"/api/analyses/{analysis_id}/phases").json()
    assert [p["key"] for p in phases["phases"]] == ["stance", "load", "swing", "follow_through"]
    assert phases["phases"][-1]["reference_frames"][1] == 80


def test_identical_to_template_scores_100(client):
    overall = _upload(client, _template_like_features()).json()["result"]["overall"]
    assert overall["score"] == 100.0
    assert overall["top_issues"] == []


def test_deviation_is_detected(client):
    features = _template_like_features()
    # 앞팔 팔꿈치를 전 구간 70도 더 굽힘. 선수 간 팔꿈치 각도 편차가 20도 정도라
    # 이 정도면 warning 이 되어야 한다.
    features[:, 57] -= 70
    result = _upload(client, features).json()["result"]
    lead_elbow = next(j for j in result["joints"] if j["key"] == "lead_elbow")
    assert lead_elbow["level"] == "warning"
    assert all(p["direction"] == "lower" for p in lead_elbow["phases"])
    other = [j for j in result["joints"] if j["key"] != "lead_elbow"]
    assert all(j["level"] == "good" for j in other)
    assert result["overall"]["top_issues"][0]["joint"] == "lead_elbow"


def test_bad_shape_rejected(client):
    response = _upload(client, np.zeros((50, 64)))
    assert response.status_code == 422


def test_unknown_analysis(client):
    assert client.get("/api/analyses/nope").status_code == 404
    assert client.get("/api/analyses/nope/overall").status_code == 404


def test_mock_mode(monkeypatch, tmp_path):
    """SWING_MOCK=1 이면 모델 없이 고정 샘플을 돌려준다 (프론트 개발용)."""
    import importlib
    import os

    monkeypatch.setenv("SWING_MOCK", "1")
    monkeypatch.chdir(tmp_path)  # users.db 가 임시 폴더에 생기도록
    import api.settings
    import api.analyses
    import api.main
    for module in (api.settings, api.analyses, api.main):
        importlib.reload(module)

    with TestClient(api.main.app) as mock_client:
        assert mock_client.get("/api/health").json()["mock"] is True
        created = mock_client.post(
            "/api/analyses",
            files={"video": ("swing.mp4", b"fake", "video/mp4")},
            data={"handedness": "right"},
        )
        assert created.status_code == 202
        analysis_id = created.json()["analysis_id"]

        analysis = mock_client.get(f"/api/analyses/{analysis_id}").json()
        assert analysis["status"] == "done"
        assert analysis["result"]["model_version"]
        assert mock_client.get(f"/api/analyses/{analysis_id}/overall").json()["available"] is True
        assert mock_client.get(f"/api/analyses/{analysis_id}/speed").json()["available"] is False
        assert mock_client.get("/api/analyses/없는id/overall").status_code == 404

    monkeypatch.delenv("SWING_MOCK")
    for module in (api.settings, api.analyses, api.main):
        importlib.reload(module)
