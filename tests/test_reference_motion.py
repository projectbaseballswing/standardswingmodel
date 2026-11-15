"""기준 동작 (feedback/reference_motion.py, /api/analyses/{id}/reference-motion)."""

import numpy as np
import pytest

from feedback.events import LEAD_HIP, LEAD_SHOULDER, REAR_HIP, REAR_SHOULDER
from feedback.reference_motion import (
    BONE_NAMES,
    JOINT_KEYS,
    assemble,
    bone_vectors,
    direction_mode,
    load_reference_motion,
    normalize_skeleton,
    user_motion,
)
from tests.video_fixture import VIDEO_BYTES


def _standing_pixel(frames: int = 40) -> np.ndarray:
    """화면 좌표(y 아래)로 선 자세. 프레임마다 조금씩 오른쪽으로 이동한다."""
    pose = np.array([
        [330, 200, 0], [270, 200, 0], [345, 260, 0], [255, 260, 0], [350, 320, 0], [250, 320, 0],
        [320, 330, 0], [280, 330, 0], [325, 420, 0], [275, 420, 0], [325, 510, 0], [275, 510, 0],
    ], dtype=float)
    return np.stack([pose + [i, 0, 0] for i in range(frames)])


def test_assemble_keeps_standard_bone_lengths_and_directions():
    rng = np.random.default_rng(0)
    directions = rng.normal(size=(5, len(BONE_NAMES), 3))
    directions /= np.linalg.norm(directions, axis=-1, keepdims=True)
    lengths = rng.uniform(0.3, 1.0, len(BONE_NAMES))

    joints = assemble(directions, lengths)
    vectors = bone_vectors(joints)
    assert np.allclose(np.linalg.norm(vectors, axis=-1), lengths)
    assert np.allclose(vectors / lengths[:, None], directions)
    assert np.allclose((joints[:, LEAD_HIP] + joints[:, REAR_HIP]) / 2, 0)


def test_direction_mode_is_not_pulled_by_outliers():
    rng = np.random.default_rng(1)
    typical = np.array([0, 1, 0]) + rng.normal(0, 0.08, (80, 3))
    outliers = np.array([1, 0, 0]) + rng.normal(0, 0.05, (20, 3))
    units = np.concatenate([typical, outliers])
    units /= np.linalg.norm(units, axis=1, keepdims=True)

    mode, spread = direction_mode(units)
    mean = units.mean(axis=0) / np.linalg.norm(units.mean(axis=0))
    angle = lambda v: np.degrees(np.arccos(np.clip(v @ [0, 1, 0], -1, 1)))
    assert angle(mode) < 3 < 10 < angle(mean)
    assert 0 < spread < 20


def test_normalize_puts_hip_center_at_origin_with_torso_length_one_and_y_up():
    joints, root = normalize_skeleton(_standing_pixel())
    hip = (joints[:, LEAD_HIP] + joints[:, REAR_HIP]) / 2
    shoulder = (joints[:, LEAD_SHOULDER] + joints[:, REAR_SHOULDER]) / 2
    assert np.allclose(hip, 0, atol=1e-9)
    assert np.allclose(np.linalg.norm((shoulder - hip)[:, :2], axis=1), 1.0, atol=1e-6)
    assert (shoulder[:, 1] > 0).all()
    assert root[-1, 0] > root[0, 0]  # 화면 오른쪽(+x) 이동이 그대로 남는다


def test_user_motion_skips_missing_phase_and_anchors_root_at_impact():
    events = {"load_start": None, "foot_lift": None, "foot_plant": 5, "swing_start": 15,
              "impact": 20, "follow_end": 30}
    motion = user_motion(_standing_pixel(), fps=30.0, events=events)
    assert set(motion["phases"]) == {"transition", "swing", "follow"}
    swing = motion["phases"]["swing"]
    assert len(swing["frames"]) == len(swing["timestamps_s"]) == len(swing["joints"]) == 20
    assert np.array(swing["joints"]).shape == (20, len(JOINT_KEYS), 3)
    assert swing["frames"][0] == 15 and swing["frames"][-1] == 20
    assert swing["timestamps_s"][-1] == pytest.approx(20 / 30, abs=1e-4)
    assert np.allclose(swing["root"][-1], 0)


def test_reference_motion_endpoint_in_mock_mode(mock_client):
    if load_reference_motion() is None:
        pytest.skip("data/reference_motion.npz 가 없습니다.")
    created = mock_client.post("/api/analyses", files={"video": ("swing.mp4", VIDEO_BYTES, "video/mp4")},
                               data={"handedness": "right"})
    analysis_id = created.json()["analysis_id"]
    # 전체 결과 응답에는 스켈레톤을 싣지 않는다 (점수 응답을 가볍게)
    assert "motion" not in mock_client.get(f"/api/analyses/{analysis_id}").json()["result"]

    response = mock_client.get(f"/api/analyses/{analysis_id}/reference-motion")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["joint_names"] == JOINT_KEYS and body["handedness"] == "right"
    assert [p["key"] for p in body["phases"]] == ["stride", "transition", "swing", "follow"]
    for phase in body["phases"]:
        ref = np.array(phase["reference"]["joints"])
        assert ref.shape == (len(phase["progress"]), 12, 3)
        lengths = np.linalg.norm(bone_vectors(ref), axis=-1)
        assert np.allclose(lengths, [b["length"] for b in body["bones"]], atol=0.01)
    assert any(p["user"] is not None for p in body["phases"])


def test_reference_motion_endpoint_404_without_stored_user_skeleton(client_with_feature_analysis):
    client, analysis_id = client_with_feature_analysis
    assert client.get(f"/api/analyses/{analysis_id}/reference-motion").status_code == 404


@pytest.fixture
def client_with_feature_analysis():
    """0.1 피처 업로드로 만든 분석 (사용자 스켈레톤이 저장되지 않는다)."""
    from fastapi.testclient import TestClient

    from api.main import app
    from tests.auth_helpers import authenticate
    from tests.test_api import _template_like_features, _upload

    with TestClient(app) as client:
        authenticate(client)
        response = _upload(client, _template_like_features())
        assert response.status_code == 200, response.text
        yield client, response.json()["analysis_id"]
