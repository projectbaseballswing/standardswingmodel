"""기준 동작(프로 대표 스켈레톤)을 만든다. 방법은 feedback/reference_motion.py 설명 참고.

기준 모델(build_reference_model.py)과 같은 스윙, 같은 이벤트, 같은 구간 길이 조건을 쓴다.
점수에는 쓰지 않는다.

사용법:
    python scripts/build_reference_motion.py                       # 프로 전체 -> data/reference_motion.npz
    python scripts/build_reference_motion.py --labeled-only --out /tmp/motion_labeled.npz   # 비교용
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feedback.reference_model import load_reference_model  # noqa: E402
from feedback.reference_motion import (  # noqa: E402
    BONE_NAMES,
    METHOD,
    MOTION_VERSION,
    PHASE_POINTS,
    assemble,
    bone_vectors,
    direction_mode,
    normalize_skeleton,
    resample_points,
)
from feedback.swing_features import DEPTH_SCALE  # noqa: E402
from scripts.build_reference_model import PHASES, load_labels, phase_windows, swing_events  # noqa: E402


def collect(skeleton_dir: Path, labels: dict, labeled_only: bool) -> tuple[dict, dict, list, int]:
    """구간별 (스윙, 시점, 뼈, 3) 뼈 벡터와 (스윙, 시점, 3) 골반 이동, 스윙별 뼈 길이."""
    bones = {key: [] for key, *_ in PHASES}
    roots = {key: [] for key, *_ in PHASES}
    lengths, used = [], 0
    for path in sorted(skeleton_dir.glob("*.npz")):
        data = np.load(path, allow_pickle=True)
        meta = json.loads(str(data["meta_json"]))
        if labeled_only and meta["video_id"] not in labels:
            continue
        events, _ = swing_events(data, labels)
        if events is None:
            continue
        fps = float(meta["fps"])
        joints, root = normalize_skeleton(data["landmarks_pixel"].astype(float))
        origin = root[events["impact"]]
        windows = [(k, s, e) for k, s, e, ok in phase_windows(events, fps) if ok]
        if not windows:
            continue
        for key, start, end in windows:
            bones[key].append(bone_vectors(resample_points(joints, start, end)))
            roots[key].append(resample_points(root - origin, start, end))
        # 표준 체형: 이 스윙에서 쓴 구간 전체 프레임의 뼈 길이 중앙값
        first, last = min(s for _, s, _ in windows), max(e for *_, e in windows)
        lengths.append(np.nanmedian(np.linalg.norm(bone_vectors(joints[first:last + 1]), axis=-1), axis=0))
        used += 1
    return bones, roots, lengths, used


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skeleton-dir", default="data/skeletons")
    parser.add_argument("--labels", default="data/labels.csv")
    parser.add_argument("--labeled-only", action="store_true", help="사람 라벨이 있는 스윙만 쓴다 (비교용)")
    parser.add_argument("--out", default="data/reference_motion.npz")
    args = parser.parse_args()

    labels = load_labels(Path(args.labels))
    bones, roots, lengths, used = collect(Path(args.skeleton_dir), labels, args.labeled_only)
    if not used:
        raise SystemExit("쓸 수 있는 스윙이 없습니다.")
    bone_lengths = np.nanmedian(np.asarray(lengths), axis=0)

    payload: dict[str, np.ndarray] = {}
    print(f"스윙 {used}개 ({'라벨만' if args.labeled_only else '프로 전체'})")
    print("표준 체형 (몸통 길이 = 1): " + ", ".join(f"{n} {v:.2f}" for n, v in zip(BONE_NAMES, bone_lengths)))
    for key, name, *_ in PHASES:
        if not bones[key]:
            print(f"  {name:12s} 표본 없음")
            continue
        vectors = np.asarray(bones[key])  # (N, points, 뼈, 3)
        units = vectors / np.linalg.norm(vectors, axis=-1, keepdims=True)
        directions = np.zeros(vectors.shape[1:])
        spread = np.zeros(vectors.shape[1:3])
        for p in range(vectors.shape[1]):
            for b in range(vectors.shape[2]):
                directions[p, b], spread[p, b] = direction_mode(units[:, p, b])
        payload[f"{key}_joints"] = assemble(directions, bone_lengths)
        payload[f"{key}_root"] = np.nanmedian(np.asarray(roots[key]), axis=0)
        payload[f"{key}_spread_deg"] = spread
        payload[f"{key}_count"] = np.asarray(len(vectors))
        print(f"  {name:12s} 스윙 {len(vectors):3d}개 | 뼈 방향 퍼짐 중앙 {np.median(spread):4.1f}도")

    reference = load_reference_model()
    payload["phase_keys"] = np.asarray([key for key, *_ in PHASES], dtype=object)
    payload["phase_points"] = np.asarray(PHASE_POINTS)
    payload["bone_lengths"] = bone_lengths
    payload["metadata_json"] = json.dumps({
        "version": MOTION_VERSION,
        "method": METHOD,
        "built_from": str(args.skeleton_dir),
        "built_on": date.today().isoformat(),
        "labeled_only": args.labeled_only,
        "swings_used": used,
        "reference_model_version": None if reference is None else reference.model_version,
        "depth_scale": DEPTH_SCALE,
    }, ensure_ascii=False)
    np.savez_compressed(args.out, **payload)
    print(f"저장: {args.out}")


if __name__ == "__main__":
    main()
