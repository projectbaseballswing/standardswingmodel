"""추출된 스켈레톤(.npz) 전체에 이벤트 검출을 돌려 결과와 분포를 본다.

사용법:
    .venv/bin/python scripts/detect_events.py --skeleton-dir data/skeletons --out data/events.csv
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

FIELDS = [
    "video_id", "fps", "n_frames",
    "load_start", "foot_lift", "foot_plant", "swing_start", "impact", "follow_end",
    "load_ms", "stride_ms", "swing_ms", "follow_through_ms",
    "nan_ratio", "warnings",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skeleton-dir", default="data/skeletons")
    parser.add_argument("--out", default="data/events.csv")
    args = parser.parse_args()

    files = sorted(Path(args.skeleton_dir).glob("*.npz"))
    print(f"스켈레톤 {len(files)}개")
    rows = []

    for path in files:
        data = np.load(path, allow_pickle=True)
        meta = json.loads(str(data["meta_json"]))
        landmarks = data["landmarks"].astype(float)
        events = detect_events(landmarks, meta["fps"], data["visibility"].astype(float))
        durations = events.phase_durations_ms()
        rows.append({
            "video_id": meta["video_id"],
            "fps": round(float(meta["fps"]), 2),
            "n_frames": events.n_frames,
            **events.as_dict(),
            "load_ms": durations["load"],
            "stride_ms": durations["stride"],
            "swing_ms": durations["swing"],
            "follow_through_ms": durations["follow_through"],
            "nan_ratio": round(float((~np.isfinite(landmarks).all(axis=(1, 2))).mean()), 3),
            "warnings": " | ".join(events.warnings),
        })

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"저장: {out}\n")

    total = len(rows)
    print("[이벤트별 검출률]")
    for name in ["load_start", "foot_lift", "foot_plant", "swing_start", "impact", "follow_end"]:
        found = sum(1 for r in rows if r[name] is not None)
        print(f"  {name:12s} {found:4d}/{total} ({100 * found / max(total, 1):3.0f}%)")

    print("\n[구간 길이 분포 (ms)]")
    for key in ["load_ms", "stride_ms", "swing_ms", "follow_through_ms"]:
        values = np.array([r[key] for r in rows if r[key] is not None], dtype=float)
        if len(values) == 0:
            print(f"  {key:18s} 없음")
            continue
        q = np.percentile(values, [10, 50, 90])
        print(f"  {key:18s} n={len(values):4d}  10% {q[0]:6.0f} / 중앙 {q[1]:6.0f} / 90% {q[2]:6.0f}")

    print("\n[경고]")
    counts: dict[str, int] = {}
    for r in rows:
        for w in filter(None, r["warnings"].split(" | ")):
            counts[w] = counts.get(w, 0) + 1
    for text, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4d}건  {text}")

    clean = sum(1 for r in rows if not r["warnings"])
    print(f"\n경고 없이 전체 이벤트가 잡힌 스윙: {clean}/{total} ({100 * clean / max(total, 1):.0f}%)")


if __name__ == "__main__":
    main()
