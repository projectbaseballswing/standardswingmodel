"""추출한 스켈레톤(.npz)의 분포를 확인한다.

어떤 이벤트까지 검출 가능한지 판단하기 위한 스크립트다.
    - fps, 길이, 임팩트 위치 분포
    - 임팩트 앞뒤로 실제 프레임이 몇 초나 있는지
    - 관절별 검출 신뢰도
    - 손목 속도 / 앞발목 높이 신호가 이벤트를 찾을 만큼 뚜렷한지

사용법:
    python scripts/inspect_skeletons.py --skeleton-dir data/skeletons
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

JOINT_NAMES = [
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]
LEAD_ANKLE, LEFT_WRIST, RIGHT_WRIST = 10, 4, 5


def percentiles(values: np.ndarray, label: str, unit: str = "") -> None:
    if len(values) == 0:
        print(f"{label}: 데이터 없음")
        return
    q = np.percentile(values, [0, 10, 25, 50, 75, 90, 100])
    print(
        f"{label}: 최소 {q[0]:.2f} / 10% {q[1]:.2f} / 25% {q[2]:.2f} / "
        f"중앙 {q[3]:.2f} / 75% {q[4]:.2f} / 90% {q[5]:.2f} / 최대 {q[6]:.2f}{unit}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skeleton-dir", default="data/skeletons")
    args = parser.parse_args()

    files = sorted(Path(args.skeleton_dir).glob("*.npz"))
    print(f"스켈레톤 파일 {len(files)}개\n")
    if not files:
        return

    fps_list, n_frames, pre_s, post_s, vis_mean = [], [], [], [], []
    hand_quiet_before, ankle_signal = [], []
    joint_vis = np.zeros(12)

    for path in files:
        data = np.load(path, allow_pickle=True)
        meta = json.loads(str(data["meta_json"]))
        lm, vis = data["landmarks"].astype(float), data["visibility"].astype(float)
        fps, impact = float(meta["fps"]), int(meta["impact_frame_hand_speed"])

        fps_list.append(fps)
        n_frames.append(lm.shape[0])
        pre_s.append(impact / fps)
        post_s.append((lm.shape[0] - impact) / fps)
        vis_mean.append(float(np.nanmean(vis)))
        joint_vis += np.nan_to_num(np.nanmean(vis, axis=0))

        # 임팩트 전에 "손이 멈춰 있는" 구간이 있는지 = 로딩 시작을 찾을 여지가 있는지
        hand = (lm[:, LEFT_WRIST, :2] + lm[:, RIGHT_WRIST, :2]) / 2
        speed = np.linalg.norm(np.diff(hand, axis=0), axis=1)
        if impact > 5 and len(speed) > impact:
            pre_speed = speed[:impact]
            quiet = np.sum(pre_speed < pre_speed.max() * 0.1) / fps
            hand_quiet_before.append(quiet)

        # 앞발목 높이 변화 = 착지 검출 가능성 (몸 크기로 정규화된 좌표)
        ankle_y = lm[:, LEAD_ANKLE, 1]
        if np.isfinite(ankle_y).sum() > 5:
            ankle_signal.append(float(np.nanmax(ankle_y) - np.nanmin(ankle_y)))

    print("[영상 길이와 타이밍]")
    from collections import Counter
    print("fps 분포:", dict(sorted(Counter(round(f) for f in fps_list).items())))
    percentiles(np.array(n_frames), "전체 프레임 수")
    percentiles(np.array(pre_s), "임팩트 앞 길이", "초")
    percentiles(np.array(post_s), "임팩트 뒤 길이", "초")

    print("\n[검출 품질]")
    percentiles(np.array(vis_mean), "평균 신뢰도")
    order = np.argsort(joint_vis / len(files))
    worst = [(JOINT_NAMES[i], round(joint_vis[i] / len(files), 3)) for i in order[:4]]
    print("신뢰도 낮은 관절:", worst)

    print("\n[이벤트 검출 가능성]")
    percentiles(np.array(hand_quiet_before), "임팩트 전 손이 멈춰 있는 시간", "초")
    print("  → 이 시간이 0에 가까우면 영상이 이미 움직이는 중에 시작한다는 뜻 (로딩 시작 검출 불가)")
    percentiles(np.array(ankle_signal), "앞발목 높이 변화 폭")
    print("  → 값이 크면 스트라이드(발 들기/착지)가 신호로 잡힌다는 뜻")

    pre = np.array(pre_s)
    print("\n[요약]")
    print(f"  임팩트 앞 1.0초 이상 확보된 영상: {(pre >= 1.0).sum()}/{len(pre)}개")
    print(f"  임팩트 앞 0.5초 미만인 영상: {(pre < 0.5).sum()}/{len(pre)}개")


if __name__ == "__main__":
    main()
