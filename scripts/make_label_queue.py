"""라벨링 우선순위 목록을 만든다.

890개를 다 라벨링할 필요는 없다. 검출기를 맞추는 데는 30~50개면 충분하지만,
그 표본이 한쪽에 몰리면 안 된다. 선수/영상 길이/fps/앞발 움직임 폭이 골고루 섞이도록 뽑는다.

사용법:
    python scripts/make_label_queue.py --count 40
    → data/label_priority.txt (라벨링 도구가 이 순서대로 먼저 보여준다)
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feedback.events import _interpolate_nan, _smooth  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skeleton-dir", default="data/skeletons")
    parser.add_argument("--out", default="data/label_priority.txt")
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--exclude-labeled", default=None,
                        help="이미 라벨링한 영상을 제외한다 (labels.csv 경로)")
    args = parser.parse_args()

    rows = []
    for path in sorted(glob.glob(f"{args.skeleton_dir}/*.npz")):
        data = np.load(path, allow_pickle=True)
        meta = json.loads(str(data["meta_json"]))
        landmarks = data["landmarks"].astype(float)
        hand = (landmarks[:, 4, :2] + landmarks[:, 5, :2]) / 2
        speed = np.hypot(
            np.diff(_smooth(_interpolate_nan(hand[:, 0]))),
            np.diff(_smooth(_interpolate_nan(hand[:, 1]))),
        )
        if len(speed) < 5 or not np.isfinite(speed).any():
            continue
        impact = int(np.nanargmax(speed[2:len(speed) - 2])) + 3
        ankle = _smooth(_interpolate_nan(landmarks[:, 10, 1]))[: impact + 1]
        lift = float(np.nanmax(ankle) - np.nanmin(ankle)) if np.isfinite(ankle).any() else np.nan
        nan_ratio = float((~np.isfinite(landmarks).all(axis=(1, 2))).mean())
        rows.append({
            "video_id": meta["video_id"],
            "player": meta["video_id"].split("_", 2)[-1],
            "fps": float(meta["fps"]),
            "duration": landmarks.shape[0] / float(meta["fps"]),
            "lift": lift,
            "nan_ratio": nan_ratio,
        })

    done: set = set()
    if args.exclude_labeled and Path(args.exclude_labeled).exists():
        import csv
        with open(args.exclude_labeled, encoding="utf-8-sig") as f:
            done = {row["video_id"] for row in csv.DictReader(f)}
        print(f"이미 라벨링한 {len(done)}개 제외")

    # 품질이 나쁜 영상은 뒤로 (라벨링해도 쓰기 어렵다)
    usable = [r for r in rows
              if r["nan_ratio"] < 0.3 and np.isfinite(r["lift"]) and r["video_id"] not in done]
    print(f"전체 {len(rows)}개 중 라벨링 대상 {len(usable)}개 (NaN 30% 미만)")

    # 길이 x 앞발 움직임 폭 으로 칸을 나누고, 칸마다 다른 선수를 돌아가며 뽑는다
    duration_edges = np.percentile([r["duration"] for r in usable], [33, 66])
    lift_edges = np.percentile([r["lift"] for r in usable], [33, 66])

    def bucket(row) -> tuple:
        return (
            int(np.digitize(row["duration"], duration_edges)),
            int(np.digitize(row["lift"], lift_edges)),
            0 if abs(row["fps"] - 30) < 2 else 1,  # 30fps 가 아닌 영상도 섞는다
        )

    groups: dict = {}
    for row in usable:
        groups.setdefault(bucket(row), []).append(row)
    for items in groups.values():
        items.sort(key=lambda r: r["nan_ratio"])  # 칸 안에서는 품질 좋은 것부터

    picked, used_players, cursor = [], set(), {key: 0 for key in groups}
    keys = sorted(groups)
    while len(picked) < args.count:
        progressed = False
        for key in keys:
            items = groups[key]
            while cursor[key] < len(items):
                row = items[cursor[key]]
                cursor[key] += 1
                # 같은 선수가 몰리지 않도록 1회전에는 선수당 1개만
                if row["player"] in used_players:
                    continue
                picked.append(row)
                used_players.add(row["player"])
                progressed = True
                break
            if len(picked) >= args.count:
                break
        if not progressed:  # 선수 제약을 풀고 다시 채운다
            used_players.clear()
            if all(cursor[key] >= len(groups[key]) for key in keys):
                break

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(r["video_id"] for r in picked) + "\n", encoding="utf-8")

    print(f"{len(picked)}개 선정 → {out}")
    print(f"  선수 {len({r['player'] for r in picked})}명")
    print("  길이: %.1f~%.1f초 (중앙 %.1f)" % (
        min(r["duration"] for r in picked), max(r["duration"] for r in picked),
        float(np.median([r["duration"] for r in picked]))))
    print("  앞발 움직임 폭: %.2f~%.2f" % (
        min(r["lift"] for r in picked), max(r["lift"] for r in picked)))
    print("  30fps 아닌 영상 %d개" % sum(1 for r in picked if abs(r["fps"] - 30) >= 2))


if __name__ == "__main__":
    main()
