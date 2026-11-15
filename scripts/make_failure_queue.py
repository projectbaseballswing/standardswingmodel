"""검출기가 틀린 것으로 보이는 영상을 먼저 라벨링하도록 순서를 만든다.

make_label_queue.py 는 검출기 임계값을 맞추려고 표본을 골고루 뽑는다.
이 스크립트는 기준 모델(build_reference_model.py)에서 빠지거나 구간이 버려지는 영상,
즉 사람 라벨이 들어가면 기준 모델이 바로 좋아지는 영상을 앞에 둔다.

우선순위 (번호가 작을수록 먼저)
    1  이벤트 순서 어긋남 / 임팩트·스윙 시작 미검출  -> 기준 모델에서 스윙 전체가 빠짐
    2  구간 길이가 허용 범위 밖                      -> 그 구간만 빠짐
    3  앞발 들기·착지·팔로우 종료 미검출, 화면 확대   -> 구간이 비거나 경계가 불확실
    4  검출은 정상                                   -> 나중에 (LSTM 학습량 늘리기용)
관절 결측이 30%를 넘는 영상은 라벨링해도 기준 모델에 못 쓰므로 목록에서 뺀다.
같은 등급 안에서는 선수를 돌아가며 뽑아 한 선수가 몰리지 않게 한다.

사용법:
    python scripts/make_failure_queue.py
    -> data/label_priority.txt   (라벨링 도구가 이 순서대로 먼저 보여준다)
       data/label_priority.csv   (영상별 등급과 이유)
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feedback.events import detect_events  # noqa: E402
from scripts.build_reference_model import MAX_NAN_RATIO, PHASE_LIMITS_MS, PHASES, load_labels  # noqa: E402

TIER_NAMES = {
    1: "기준 모델에서 제외됨",
    2: "구간 길이 이상",
    3: "이벤트 미검출/화면 확대",
    4: "검출 정상",
}


def classify(pixel: np.ndarray, fps: float) -> tuple[int, list[str]]:
    events = detect_events(pixel, fps)
    ev = events.as_dict()

    if ev["impact"] is None or ev["swing_start"] is None:
        return 1, ["임팩트/스윙 시작 없음"]
    order = [(k, ev[k]) for k in ("foot_lift", "foot_plant", "swing_start", "impact", "follow_end") if ev[k] is not None]
    if any(b[1] < a[1] for a, b in zip(order, order[1:])):
        return 1, ["이벤트 순서 어긋남"]

    reasons = []
    for key, name, start_key, end_key in PHASES:
        start, end = ev[start_key], ev[end_key]
        if start is None or end is None:
            continue
        ms = (end - start) / fps * 1000
        low, high = PHASE_LIMITS_MS[key]
        if not low <= ms <= high:
            reasons.append(f"{name} {ms:.0f}ms")
    if reasons:
        return 2, reasons

    missing = [k for k in ("foot_lift", "foot_plant", "follow_end") if ev[k] is None]
    if missing:
        reasons.append("미검출: " + ",".join(missing))
    if events.zoom_frame is not None:
        reasons.append(f"화면 확대 {events.zoom_frame}프레임")
    if reasons:
        return 3, reasons
    return 4, []


def round_robin_by_player(rows: list[dict]) -> list[dict]:
    by_player: dict[str, list[dict]] = {}
    for row in rows:
        by_player.setdefault(row["player"], []).append(row)
    queues = [by_player[p] for p in sorted(by_player)]
    out = []
    while any(queues):
        for queue in queues:
            if queue:
                out.append(queue.pop(0))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skeleton-dir", default="data/skeletons")
    parser.add_argument("--labels", default="data/labels.csv")
    parser.add_argument("--out", default="data/label_priority.txt")
    parser.add_argument("--csv", default="data/label_priority.csv")
    args = parser.parse_args()

    done = set(load_labels(Path(args.labels)))
    rows, skipped_nan = [], 0
    for path in sorted(Path(args.skeleton_dir).glob("*.npz")):
        data = np.load(path, allow_pickle=True)
        meta = json.loads(str(data["meta_json"]))
        video_id = meta["video_id"]
        if video_id in done:
            continue
        nan_ratio = float((~np.isfinite(data["landmarks"].astype(float)).all(axis=(1, 2))).mean())
        if nan_ratio > MAX_NAN_RATIO:
            skipped_nan += 1
            continue
        tier, reasons = classify(data["landmarks_pixel"].astype(float), float(meta["fps"]))
        rows.append({
            "video_id": video_id,
            "player": video_id.split("_", 2)[-1],
            "tier": tier,
            "reason": "; ".join(reasons),
        })

    ordered = []
    for tier in sorted(TIER_NAMES):
        ordered += round_robin_by_player([r for r in rows if r["tier"] == tier])

    out = Path(args.out)
    if out.exists():
        backup = out.with_name(out.stem + "_before_failure" + out.suffix)
        shutil.copyfile(out, backup)
        print(f"기존 목록 백업 -> {backup}")
    out.write_text("\n".join(r["video_id"] for r in ordered) + "\n", encoding="utf-8")
    with open(args.csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["rank", "video_id", "tier", "tier_name", "reason"])
        writer.writeheader()
        for rank, r in enumerate(ordered, 1):
            writer.writerow({"rank": rank, "video_id": r["video_id"], "tier": r["tier"],
                             "tier_name": TIER_NAMES[r["tier"]], "reason": r["reason"]})

    print(f"라벨링 완료 {len(done)}개 제외, 관절 결측 많음 {skipped_nan}개 제외")
    print(f"목록 {len(ordered)}개 -> {out}, {args.csv}")
    for tier, name in TIER_NAMES.items():
        n = sum(1 for r in rows if r["tier"] == tier)
        print(f"  {tier}등급 {name:16s} {n:4d}개")


if __name__ == "__main__":
    main()
