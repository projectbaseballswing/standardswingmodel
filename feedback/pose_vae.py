"""VAE 개선 자세: 사용자 스윙을 '프로다운' 스윙으로 옮긴 자세를 만든다 (점수에는 쓰지 않는다).

프로 스윙의 뼈 방향 시퀀스(구간 4개 x 20 시점 x 뼈 11개)로 시퀀스 VAE 를 학습한다.
사용자 스윙을 인코더로 잠재 공간에 넣고 디코더로 다시 꺼내면, 프로 스윙에서 본 적 없는 부분(실수)은
프로다운 모양으로 바뀌고 프로에게도 흔한 부분(스타일)은 남는다. 관절을 따로 고치지 않고 스윙 전체를
한꺼번에 다시 만들기 때문에, 한 관절이 바뀌면 함께 움직이는 관절도 같이 맞춰진다.

뼈 길이는 모델에 넣지 않는다. 개선 자세는 사용자 자신의 뼈 길이로 조립해서 체형이 그대로 남는다.
학습은 scripts/train_pose_vae.py (PyTorch), 여기서는 NumPy 로만 계산한다 (API 서버에는 PyTorch 가 없다).
모델 파일이 없으면 load_pose_vae() 가 None 을 돌려주고 API 는 개선 자세 없이 응답한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from feedback.event_lstm import _lstm_direction
from feedback.reference_motion import BONE_NAMES, PHASE_POINTS, assemble, bone_vectors

VAE_VERSION = "pose-vae-v1"
DEFAULT_POSE_VAE_PATH = Path(__file__).resolve().parent / "pose_vae.npz"
PHASE_KEYS: List[str] = ["stride", "transition", "swing", "follow"]
N_BONES = len(BONE_NAMES)
SEQ_LEN = len(PHASE_KEYS) * PHASE_POINTS
PHASE_LABELS = {"stride": "스트라이드", "transition": "착지 후 준비", "swing": "스윙", "follow": "팔로우스루"}
BONE_LABELS = {
    "pelvis": "골반", "spine": "몸통", "shoulders": "어깨선",
    "lead_upper_arm": "앞팔 위팔", "lead_forearm": "앞팔 아래팔", "rear_upper_arm": "뒷팔 위팔", "rear_forearm": "뒷팔 아래팔",
    "lead_thigh": "앞다리 허벅지", "lead_shin": "앞다리 정강이", "rear_thigh": "뒷다리 허벅지", "rear_shin": "뒷다리 정강이",
}


def phase_directions(phases: Dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """{구간: {"joints": (20, 12, 3)}} -> (80, 11, 3) 뼈 단위 방향, (80,) 있는 시점 표시.

    구간이 없으면 그 20 시점은 0 이고 mask 가 False 다.
    """
    dirs = np.zeros((SEQ_LEN, N_BONES, 3))
    mask = np.zeros(SEQ_LEN, dtype=bool)
    for p, key in enumerate(PHASE_KEYS):
        phase = phases.get(key)
        if not phase:
            continue
        joints = np.asarray(phase["joints"], dtype=float)
        vectors = bone_vectors(joints)
        norm = np.linalg.norm(vectors, axis=-1, keepdims=True)
        if not np.isfinite(vectors).all() or (norm < 1e-6).any():
            continue
        sl = slice(p * PHASE_POINTS, (p + 1) * PHASE_POINTS)
        dirs[sl] = vectors / norm
        mask[sl] = True
    return dirs, mask


def model_inputs(dirs: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """(80, 11, 3), (80,) -> (80, 39) 인코더 입력: 뼈 방향 33 + 구간 표시 4 + 구간 진행률 1 + 있음 1."""
    return np.hstack([(dirs * mask[:, None, None]).reshape(SEQ_LEN, -1), time_inputs(), mask[:, None].astype(float)])


def time_inputs() -> np.ndarray:
    """(80, 5) 구간 표시(one-hot 4) + 구간 진행률(0~1)."""
    phase = np.repeat(np.eye(len(PHASE_KEYS)), PHASE_POINTS, axis=0)
    progress = np.tile(np.linspace(0, 1, PHASE_POINTS), len(PHASE_KEYS))[:, None]
    return np.hstack([phase, progress])


def _bilstm(x: np.ndarray, w: Dict[str, np.ndarray], prefix: str) -> np.ndarray:
    fwd = _lstm_direction(x, w[f"{prefix}weight_ih_l0"], w[f"{prefix}weight_hh_l0"],
                          w[f"{prefix}bias_ih_l0"] + w[f"{prefix}bias_hh_l0"])
    bwd = _lstm_direction(x[::-1], w[f"{prefix}weight_ih_l0_reverse"], w[f"{prefix}weight_hh_l0_reverse"],
                          w[f"{prefix}bias_ih_l0_reverse"] + w[f"{prefix}bias_hh_l0_reverse"])[::-1]
    return np.hstack([fwd, bwd])


@dataclass
class PoseVAE:
    weights: Dict[str, np.ndarray]
    metadata: Dict[str, Any]

    def encode(self, dirs: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """잠재 평균 (latent,). 없는 구간은 빼고 평균을 낸다."""
        w = self.weights
        h = _bilstm(model_inputs(dirs, mask), w, "enc.")
        pooled = (h * mask[:, None]).sum(0) / max(1, mask.sum())
        return pooled @ w["mu.weight"].T + w["mu.bias"]

    def decode(self, z: np.ndarray) -> np.ndarray:
        """(latent,) -> (80, 11, 3) 뼈 단위 방향."""
        w = self.weights
        x = np.hstack([np.repeat(z[None], SEQ_LEN, axis=0), time_inputs()])
        out = _bilstm(x, w, "dec.") @ w["out.weight"].T + w["out.bias"]
        out = out.reshape(SEQ_LEN, N_BONES, 3)
        return out / np.maximum(np.linalg.norm(out, axis=-1, keepdims=True), 1e-9)

    def improve(self, dirs: np.ndarray, mask: np.ndarray) -> np.ndarray:
        return self.decode(self.encode(dirs, mask))


_CACHE: Dict[str, Optional[PoseVAE]] = {}


def load_pose_vae(path: str = str(DEFAULT_POSE_VAE_PATH)) -> Optional[PoseVAE]:
    if path in _CACHE:
        return _CACHE[path]
    file = Path(path)
    model = None
    if file.exists():
        import json

        data = np.load(file, allow_pickle=False)
        weights = {k[2:]: data[k].astype(np.float64) for k in data.files if k.startswith("w_")}
        model = PoseVAE(weights=weights, metadata=json.loads(str(data["metadata_json"])))
    _CACHE[path] = model
    return model


def angle_deg(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.degrees(np.arccos(np.clip((a * b).sum(-1), -1.0, 1.0)))


def improved_motion(model: PoseVAE, phases: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """저장된 사용자 동작(user_motion 의 phases) -> 구간별 개선 자세.

    {구간: {"joints": (20, 12, 3), "change_deg": (20, 11)}}, 고친 정도가 큰 뼈 요약 "largest_changes".
    """
    dirs, mask = phase_directions(phases)
    if not mask.any():
        return None
    improved = model.improve(dirs, mask)
    change = angle_deg(improved, dirs)

    # 사용자 체형: 사용자 자세 전체 시점의 뼈 길이 중앙값
    all_joints = np.concatenate([np.asarray(phases[k]["joints"], dtype=float) for k in PHASE_KEYS if phases.get(k)])
    lengths = np.nanmedian(np.linalg.norm(bone_vectors(all_joints), axis=-1), axis=0)

    out: Dict[str, Any] = {}
    summary = []
    for p, key in enumerate(PHASE_KEYS):
        sl = slice(p * PHASE_POINTS, (p + 1) * PHASE_POINTS)
        if not mask[sl].all():
            continue
        out[key] = {
            "joints": np.round(assemble(improved[sl], lengths), 3).tolist(),
            "change_deg": np.round(change[sl], 1).tolist(),
        }
        for b, name in enumerate(BONE_NAMES):
            summary.append({"phase": key, "phase_name": PHASE_LABELS[key], "bone": name, "bone_name": BONE_LABELS[name],
                            "max_change_deg": round(float(change[sl, b].max()), 1),
                            "at_point": int(change[sl, b].argmax())})
    summary.sort(key=lambda s: -s["max_change_deg"])
    return {"version": model.metadata.get("version", VAE_VERSION), "phases": out, "largest_changes": summary[:5]}
