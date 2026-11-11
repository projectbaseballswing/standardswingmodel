"""VAE 개선 자세 (feedback/pose_vae.py, /reference-motion 의 improved)."""

import numpy as np
import pytest

from feedback.pose_vae import (
    N_BONES, PHASE_KEYS, SEQ_LEN, PoseVAE, improved_motion, load_pose_vae, phase_directions, time_inputs,
)
from feedback.reference_motion import bone_vectors, user_motion
from tests.test_reference_motion import _standing_pixel
from tests.video_fixture import VIDEO_BYTES


def _random_vae(hidden: int = 8, latent: int = 4, seed: int = 0) -> PoseVAE:
    rng = np.random.default_rng(seed)
    w = {}
    for prefix, in_dim in (("enc.", N_BONES * 3 + time_inputs().shape[1] + 1), ("dec.", latent + time_inputs().shape[1])):
        for suffix in ("", "_reverse"):
            w[f"{prefix}weight_ih_l0{suffix}"] = rng.normal(0, 0.3, (4 * hidden, in_dim))
            w[f"{prefix}weight_hh_l0{suffix}"] = rng.normal(0, 0.3, (4 * hidden, hidden))
            w[f"{prefix}bias_ih_l0{suffix}"] = rng.normal(0, 0.1, 4 * hidden)
            w[f"{prefix}bias_hh_l0{suffix}"] = rng.normal(0, 0.1, 4 * hidden)
    w["mu.weight"], w["mu.bias"] = rng.normal(0, 0.3, (latent, 2 * hidden)), np.zeros(latent)
    w["out.weight"], w["out.bias"] = rng.normal(0, 0.3, (N_BONES * 3, 2 * hidden)), rng.normal(0, 0.3, N_BONES * 3)
    return PoseVAE(weights=w, metadata={"version": "test"})


def _stored_phases():
    events = {"load_start": None, "foot_lift": None, "foot_plant": 5, "swing_start": 15, "impact": 20, "follow_end": 30}
    return user_motion(_standing_pixel(), fps=30.0, events=events)["phases"]


def test_phase_directions_marks_missing_phase():
    dirs, mask = phase_directions(_stored_phases())
    assert dirs.shape == (SEQ_LEN, N_BONES, 3)
    assert not mask[:20].any() and mask[20:].all()  # 스트라이드 없음
    assert np.allclose(np.linalg.norm(dirs[mask], axis=-1), 1.0)


def test_improved_motion_keeps_user_bone_lengths_and_skips_missing_phase():
    phases = _stored_phases()
    result = improved_motion(_random_vae(), phases)
    assert set(result["phases"]) == {"transition", "swing", "follow"}

    user_joints = np.concatenate([np.asarray(phases[k]["joints"]) for k in PHASE_KEYS if k in phases])
    user_lengths = np.median(np.linalg.norm(bone_vectors(user_joints), axis=-1), axis=0)
    for key, phase in result["phases"].items():
        joints = np.asarray(phase["joints"])
        assert joints.shape == (20, 12, 3)
        assert np.allclose(np.linalg.norm(bone_vectors(joints), axis=-1), user_lengths, atol=0.01)
        assert np.asarray(phase["change_deg"]).shape == (20, N_BONES)
        assert len(phase["applied"]) == 20 and all(a == 1.0 for a in phase["applied"])  # 기준 정보가 없으면 전부 적용

    changes = [c["max_change_deg"] for c in result["largest_changes"]]
    assert len(changes) == 5 and changes == sorted(changes, reverse=True)
    assert all(c["phase"] != "stride" and c["bone_name"] for c in result["largest_changes"])


def test_gate_keeps_user_pose_when_nothing_is_unusual():
    # VAE 가 바꾸려는 정도가 '보통' 수준이면 적용하지 않고 사용자 자세를 그대로 둔다
    phases = _stored_phases()
    dirs, mask = phase_directions(phases)
    model = _random_vae()
    model.floor_deg = np.full((SEQ_LEN, N_BONES), 180.0)
    improved, applied = model.improve(dirs, mask)
    assert np.allclose(applied, 0.0)
    assert np.allclose(improved[mask], dirs[mask])
    result = improved_motion(model, phases)
    assert result["largest_changes"] == []


def test_gate_applies_only_around_unusual_moments():
    phases = _stored_phases()
    dirs, mask = phase_directions(phases)
    model = _random_vae()
    from feedback.pose_vae import angle_deg
    change = angle_deg(model.reconstruct(dirs, mask), dirs)
    floor = np.full((SEQ_LEN, N_BONES), 180.0)
    floor[45] = np.maximum(change[45] / 10, 0.1)  # 스윙 구간 한 시점만 '보통보다 훨씬 크게' 바뀌는 상황
    model.floor_deg = floor
    _, applied = model.improve(dirs, mask)
    assert applied[45] > 0.5
    assert applied[:40].max() == 0 and applied[60:].max() == 0  # 다른 구간은 그대로


def test_reference_motion_endpoint_includes_improved_pose(mock_client):
    from feedback.reference_motion import load_reference_motion

    if load_reference_motion() is None or load_pose_vae() is None:
        pytest.skip("data/reference_motion.npz 또는 feedback/pose_vae.npz 가 없습니다.")
    created = mock_client.post("/api/analyses", files={"video": ("swing.mp4", VIDEO_BYTES, "video/mp4")},
                               data={"handedness": "right"})
    body = mock_client.get(f"/api/analyses/{created.json()['analysis_id']}/reference-motion").json()
    assert isinstance(body["improvement"]["largest_changes"], list)  # 프로 샘플이면 비어 있을 수 있다
    for phase in body["phases"]:
        if phase["user"] is None:
            assert phase["improved"] is None
        else:
            assert np.asarray(phase["improved"]["joints"]).shape == np.asarray(phase["user"]["joints"]).shape


def test_shadow_scores_are_stored_but_not_returned(monkeypatch):
    # VAE 거리는 결과에 기록만 하고 API 응답(AnalysisReport)에는 나가지 않는다
    import json
    from pathlib import Path

    import feedback.pose_vae as pose_vae
    from api.jobs import _attach_shadow_scores
    from api.schemas import AnalysisReport

    model = _random_vae()
    model.floor_deg = np.full((SEQ_LEN, N_BONES), 5.0)
    monkeypatch.setattr(pose_vae, "load_pose_vae", lambda *a, **k: model)

    result = json.loads(Path("api/fixtures/analysis_sample.json").read_text(encoding="utf-8"))
    _attach_shadow_scores(result)
    scores = result["shadow_scores"]["pose_vae"]
    assert {"version", "change_deg", "ratio_rms", "applied", "points"} <= set(scores)
    assert scores["change_deg"] >= 0 and 0 <= scores["applied"] <= 1
    assert "shadow_scores" not in AnalysisReport.model_validate(result).model_dump()
