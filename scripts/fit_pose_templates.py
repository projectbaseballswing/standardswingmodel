"""라벨에서 이벤트별 '기준 자세'를 만들어 저장한다.

규칙(속도·발목 움직임)이 찾은 프레임 주변에서, 자세가 기준과 가장 비슷한 프레임으로 보정하는 데 쓴다.

사용법:
    python scripts/fit_pose_templates.py --limit 48     # 앞 48개(학습용)로만 만들기
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feedback.events import _scale_per_frame, find_zoom_frame, pose_vector  # noqa: E402

KEYS = ["impact", "foot_plant", "swing_start"]
DEFAULT_OUT = "feedback/pose_templates.npz"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", default="data/labels.csv")
    parser.add_argument("--skeleton-dir", default="data/skeletons")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=0, help="앞에서 N개만 사용 (0=전체)")
    args = parser.parse_args()

    rows = list(csv.DictReader(Path(args.labels).open(encoding="utf-8-sig")))
    if args.limit:
        rows = rows[: args.limit]

    collected: dict[str, list[np.ndarray]] = {key: [] for key in KEYS}
    for row in rows:
        path = Path(args.skeleton_dir) / f"{row['video_id']}.npz"
        if not path.exists():
            continue
        pixel = np.load(path, allow_pickle=True)["landmarks_pixel"].astype(float)
        poses = pose_vector(pixel, _scale_per_frame(pixel, find_zoom_frame(pixel)))
        for key in KEYS:
            value = row.get(key)
            if value and 0 <= int(value) < len(poses):
                collected[key].append(poses[int(value)])

    payload = {}
    for key, items in collected.items():
        arr = np.asarray(items, dtype=float)
        payload[f"{key}_mean"] = arr.mean(axis=0)
        # 선수마다 많이 다른 관절은 가중치를 낮추기 위해 편차를 함께 저장한다
        payload[f"{key}_spread"] = arr.std(axis=0) + 0.05
        print(f"{key:12s} {len(items):3d}개 프레임으로 생성")

    payload["label_count"] = np.asarray(len(rows))
    np.savez(args.out, **payload)
    print("저장:", args.out)


if __name__ == "__main__":
    main()
