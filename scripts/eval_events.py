"""검출기(feedback/events.py)를 사람이 찍은 라벨(data/labels.csv)과 비교한다.

라벨이 늘어날 때마다 다시 돌려서 정확도가 개선됐는지 확인한다.

사용법:
    python scripts/eval_events.py
    python scripts/eval_events.py --since 2026-09-30   # 이 날짜 이후 라벨만 (검증용)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feedback.events import detect_events  # noqa: E402

KEYS = ["load_start", "foot_lift", "foot_plant", "swing_start", "impact", "follow_end"]
KEY_NAMES = {
    "load_start": "로딩 시작", "foot_lift": "앞발 들기", "foot_plant": "앞발 착지",
    "swing_start": "스윙 시작", "impact": "임팩트", "follow_end": "팔로우 종료",
}


def num(value) -> int | None:
    return int(value) if value not in (None, "") else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", default="data/labels.csv")
    parser.add_argument("--skeleton-dir", default="data/skeletons")
    parser.add_argument("--since", default=None, help="이 날짜(YYYY-MM-DD) 이후 라벨만 사용")
    parser.add_argument("--details", action="store_true", help="오차가 큰 사례 출력")
    args = parser.parse_args()

    rows = list(csv.DictReader(Path(args.labels).open(encoding="utf-8-sig")))
    if args.since:
        rows = [r for r in rows if r.get("labeled_at", "") >= args.since]
    print(f"라벨 {len(rows)}개")

    errors: dict[str, list[tuple[str, int]]] = {key: [] for key in KEYS}
    missing = {key: 0 for key in KEYS}
    labeled = {key: 0 for key in KEYS}

    for row in rows:
        path = Path(args.skeleton_dir) / f"{row['video_id']}.npz"
        if not path.exists():
            continue
        data = np.load(path, allow_pickle=True)
        meta = json.loads(str(data["meta_json"]))
        events = detect_events(
            data["landmarks_pixel"].astype(float),
            meta["fps"],
            clip_start=num(row.get("clip_start")) or 0,
            clip_end=num(row.get("clip_end")),
        ).as_dict()

        for key in KEYS:
            label = num(row.get(key))
            if label is None:
                continue
            labeled[key] += 1
            if events[key] is None:
                missing[key] += 1
            else:
                errors[key].append((row["video_id"], events[key] - label))

    print()
    print("%-12s %6s %6s %8s %8s %7s %7s" % ("이벤트", "라벨", "미검출", "평균오차", "중앙오차", "±2이내", "±3이내"))
    for key in KEYS:
        values = np.array([e for _, e in errors[key]])
        if not len(values):
            print("%-12s %6d %6d %8s" % (KEY_NAMES[key], labeled[key], missing[key], "-"))
            continue
        print("%-12s %6d %6d %+8.1f %+8.0f %6.0f%% %6.0f%%" % (
            KEY_NAMES[key], labeled[key], missing[key],
            values.mean(), np.median(values),
            100 * np.mean(np.abs(values) <= 2), 100 * np.mean(np.abs(values) <= 3),
        ))
    print("\n(오차 = 검출 - 라벨. +는 검출이 늦게 잡았다는 뜻)")

    if args.details:
        print("\n[오차 5프레임 초과 사례]")
        for key in KEYS:
            bad = [(vid, err) for vid, err in errors[key] if abs(err) > 5]
            if bad:
                print(f"  {KEY_NAMES[key]}: " + ", ".join(f"{vid}({err:+d})" for vid, err in bad))


if __name__ == "__main__":
    main()
