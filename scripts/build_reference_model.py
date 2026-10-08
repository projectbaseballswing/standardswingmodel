"""이벤트 기반 기준 스윙 모델을 만든다.

기존 모델과의 차이
    기존: 임팩트 기준 80프레임으로 자르고(모자라면 복사) 프레임 번호끼리 평균
    신규: 동작 사건으로 구간을 나누고, 구간마다 0~100% 로 시간 정규화해서 평균

구간 구성
    stride      앞발 들기 -> 앞발 착지
    transition  앞발 착지 -> 스윙 시작
    swing       스윙 시작 -> 임팩트
    follow      임팩트 -> 팔로우 종료

각 구간은 "양쪽 이벤트가 모두 있는 스윙"만 모아서 평균/편차를 내고, 표본 수(n)를 함께 저장한다.
영상에 담기지 않은 구간은 그 스윙에서 빠질 뿐, 다른 구간은 그대로 쓰인다.

사용법:
    python scripts/build_reference_model.py --out data/reference_model.npz
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
from feedback.swing_features import FEATURE_NAMES, compute_features, hand_speed  # noqa: E402

PHASES = [
    ("stride", "스트라이드", "foot_lift", "foot_plant"),
    ("transition", "착지 후 준비", "foot_plant", "swing_start"),
    ("swing", "스윙", "swing_start", "impact"),
    ("follow", "팔로우스루", "impact", "follow_end"),
]
PHASE_POINTS = 20  # 구간마다 0~100% 를 몇 등분해서 저장할지
MAX_NAN_RATIO = 0.3

# 구간 길이가 이 범위를 벗어나면 그 구간만 제외한다 (검출 실패로 본다).
# 라벨 78개 분포의 바깥쪽을 넉넉히 잡았다.
PHASE_LIMITS_MS = {
    "stride": (150, 2500),
    "transition": (0, 1200),
    "swing": (50, 500),
    "follow": (50, 1200),
}
# 임팩트 기준 각 이벤트 시점(ms)도 함께 저장한다. 구간 길이보다 덜 흔들린다.
TIMING_KEYS = ["load_start", "foot_lift", "foot_plant", "swing_start", "follow_end"]


def num(value) -> int | None:
    return int(value) if value not in (None, "") else None


def load_labels(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig") as f:
        return {row["video_id"]: row for row in csv.DictReader(f)}


def resample_phase(features: np.ndarray, start: int, end: int, points: int = PHASE_POINTS) -> np.ndarray | None:
    """구간 [start, end] 을 0~100% 로 늘이거나 줄여서 points 개로 맞춘다."""
    if end <= start or start < 0 or end >= len(features):
        return None
    source = np.arange(start, end + 1)
    target = np.linspace(start, end, points)
    return np.stack([np.interp(target, source, features[start:end + 1, col]) for col in range(features.shape[1])], axis=1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skeleton-dir", default="data/skeletons")
    parser.add_argument("--labels", default="data/labels.csv")
    parser.add_argument("--out", default="data/reference_model.npz")
    parser.add_argument("--summary", default="data/reference_model_summary.csv")
    args = parser.parse_args()

    labels = load_labels(Path(args.labels))
    files = sorted(Path(args.skeleton_dir).glob("*.npz"))
    print(f"스켈레톤 {len(files)}개 / 라벨 {len(labels)}개\n")

    phase_curves: dict[str, list] = {key: [] for key, *_ in PHASES}
    phase_durations: dict[str, list] = {key: [] for key, *_ in PHASES}
    timings: dict[str, list] = {key: [] for key in TIMING_KEYS}
    speed_rows, summary_rows = [], []
    used, skipped, dropped_phases = 0, {}, {}

    for path in files:
        data = np.load(path, allow_pickle=True)
        meta = json.loads(str(data["meta_json"]))
        video_id = meta["video_id"]
        pixel = data["landmarks_pixel"].astype(float)
        row = {"video_id": video_id, "fps": round(float(meta["fps"]), 2), "status": "ok", "reason": ""}

        nan_ratio = float((~np.isfinite(data["landmarks"].astype(float)).all(axis=(1, 2))).mean())
        row["nan_ratio"] = round(nan_ratio, 3)
        if nan_ratio > MAX_NAN_RATIO:
            row.update(status="skipped", reason="관절 결측이 많음")
            summary_rows.append(row); skipped["관절 결측이 많음"] = skipped.get("관절 결측이 많음", 0) + 1
            continue

        label = labels.get(video_id, {})
        events = detect_events(
            pixel, meta["fps"],
            clip_start=num(label.get("clip_start")) or 0,
            clip_end=num(label.get("clip_end")),
        ).as_dict()
        # 사람이 찍은 라벨이 있으면 그 값을 우선한다
        for key in events:
            if num(label.get(key)) is not None:
                events[key] = num(label[key])
        row["labeled"] = bool(label)

        if events["impact"] is None or events["swing_start"] is None:
            row.update(status="skipped", reason="임팩트/스윙 시작 없음")
            summary_rows.append(row); skipped["임팩트/스윙 시작 없음"] = skipped.get("임팩트/스윙 시작 없음", 0) + 1
            continue

        order = [events[k] for k in ("foot_lift", "foot_plant", "swing_start", "impact", "follow_end") if events[k] is not None]
        if any(b < a for a, b in zip(order, order[1:])):
            row.update(status="skipped", reason="이벤트 순서 어긋남")
            summary_rows.append(row); skipped["이벤트 순서 어긋남"] = skipped.get("이벤트 순서 어긋남", 0) + 1
            continue

        features = compute_features(pixel)
        fps = float(meta["fps"])
        for key, _, start_key, end_key in PHASES:
            start, end = events[start_key], events[end_key]
            if start is None or end is None:
                continue
            duration_ms = (end - start) / fps * 1000
            low, high = PHASE_LIMITS_MS[key]
            if not low <= duration_ms <= high:
                dropped_phases[key] = dropped_phases.get(key, 0) + 1
                continue
            curve = resample_phase(features, start, end)
            if curve is None:
                continue
            phase_curves[key].append(curve)
            phase_durations[key].append((end - start) / fps * 1000)
            row[f"{key}_ms"] = round((end - start) / fps * 1000)

        impact = events["impact"]
        for key in TIMING_KEYS:
            if events.get(key) is not None:
                timings[key].append((events[key] - impact) / fps * 1000)

        speed = hand_speed(pixel, fps)
        window = speed[max(0, impact - 5):min(len(speed), impact + 3)]
        speed_rows.append({
            "swing_time_ms": (impact - events["swing_start"]) / fps * 1000,
            "peak_hand_speed": float(np.max(window)) if len(window) else np.nan,
            "plant_to_impact_ms": ((impact - events["foot_plant"]) / fps * 1000) if events["foot_plant"] is not None else np.nan,
        })
        used += 1
        summary_rows.append(row)

    # ------------------------------------------------------------------
    payload: dict[str, np.ndarray] = {}
    print("[구간별 기준 곡선]")
    for key, name, *_ in PHASES:
        curves = np.asarray(phase_curves[key], dtype=float)
        if not len(curves):
            print(f"  {name:12s} 표본 없음")
            continue
        payload[f"{key}_mean"] = np.nanmean(curves, axis=0)
        payload[f"{key}_std"] = np.nanstd(curves, axis=0)
        payload[f"{key}_count"] = np.asarray(len(curves))
        durations = np.asarray(phase_durations[key], dtype=float)
        payload[f"{key}_duration_mean"] = np.asarray(float(np.mean(durations)))
        payload[f"{key}_duration_std"] = np.asarray(float(np.std(durations)))
        print(f"  {name:12s} 스윙 {len(curves):3d}개 | 길이 {np.mean(durations):6.0f} ± {np.std(durations):5.0f} ms "
              f"(중앙 {np.median(durations):.0f})")

    print("\n[임팩트 기준 이벤트 시점 (ms, -는 임팩트 이전)]")
    for key in TIMING_KEYS:
        values = np.asarray(timings[key], dtype=float)
        values = values[np.isfinite(values)]
        if not len(values):
            continue
        # 분포 양 끝 5%는 검출 실패로 보고 제외한 뒤 평균/편차를 낸다
        low, high = np.percentile(values, [5, 95])
        trimmed = values[(values >= low) & (values <= high)]
        payload[f"timing_{key}_mean"] = np.asarray(float(trimmed.mean()))
        payload[f"timing_{key}_std"] = np.asarray(float(trimmed.std()))
        payload[f"timing_{key}_count"] = np.asarray(len(trimmed))
        print(f"  {key:12s} n={len(trimmed):3d}  {trimmed.mean():+7.0f} ± {trimmed.std():5.0f}")

    print("\n[속도 지표]")
    for key in ("swing_time_ms", "peak_hand_speed", "plant_to_impact_ms"):
        values = np.asarray([r[key] for r in speed_rows], dtype=float)
        values = values[np.isfinite(values)]
        low, high = np.percentile(values, [5, 95])  # 추적 실패로 튄 값 제외
        values = values[(values >= low) & (values <= high)]
        payload[f"speed_{key}_mean"] = np.asarray(float(values.mean()))
        payload[f"speed_{key}_std"] = np.asarray(float(values.std()))
        payload[f"speed_{key}_count"] = np.asarray(len(values))
        print(f"  {key:20s} n={len(values):3d}  {values.mean():7.1f} ± {values.std():5.1f}  "
              f"(10% {np.percentile(values,10):.1f} / 90% {np.percentile(values,90):.1f})")

    # 점수 환산 기준: 기준 스윙 하나하나가 평균 곡선에서 얼마나 떨어져 있는지
    # (사용자 점수를 "프로 스윙은 보통 이 정도 거리"와 견주기 위해 저장한다)
    distances = []
    for index in range(max((len(phase_curves[key]) for key, *_ in PHASES), default=0)):
        diffs = []
        for key, *_ in PHASES:
            curves = phase_curves[key]
            if index >= len(curves):
                continue
            spread = np.maximum(payload[f"{key}_std"], 1e-6)
            diffs.append(np.abs(curves[index] - payload[f"{key}_mean"]) / spread)
        if diffs:
            distances.append(float(np.sqrt(np.mean(np.concatenate(diffs) ** 2))))
    distances = np.asarray(distances, dtype=float)
    if len(distances):
        low, high = np.percentile(distances, [5, 95])
        trimmed = distances[(distances >= low) & (distances <= high)]
        payload["typical_distance"] = np.asarray(float(np.median(trimmed)))
        payload["typical_distance_std"] = np.asarray(float(trimmed.std()))
        print("\n[점수 환산 기준] 기준 스윙이 평균에서 떨어진 거리: 중앙 %.2f (10%% %.2f / 90%% %.2f)"
              % (np.median(trimmed), np.percentile(distances, 10), np.percentile(distances, 90)))

    payload["feature_names"] = np.asarray(FEATURE_NAMES, dtype=object)
    payload["phase_keys"] = np.asarray([key for key, *_ in PHASES], dtype=object)
    payload["phase_points"] = np.asarray(PHASE_POINTS)
    payload["metadata_json"] = json.dumps({
        "model_version": "0.2-draft",
        "built_from": str(args.skeleton_dir),
        "swings_total": len(files),
        "swings_used": used,
        "skipped": skipped,
        "labels_used": sum(1 for r in summary_rows if r.get("labeled")),
        "phase_points": PHASE_POINTS,
        "max_nan_ratio": MAX_NAN_RATIO,
        "phase_limits_ms": PHASE_LIMITS_MS,
        "dropped_phases": dropped_phases,
    }, ensure_ascii=False)

    np.savez_compressed(args.out, **payload)
    fieldnames = ["video_id", "status", "reason", "fps", "nan_ratio", "labeled",
                  *[f"{key}_ms" for key, *_ in PHASES]]
    with Path(args.summary).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"\n사용 {used} / 전체 {len(files)}")
    for key, count in sorted(dropped_phases.items(), key=lambda kv: -kv[1]):
        print(f"  구간 제외 {count:3d}개: {key} (길이가 {PHASE_LIMITS_MS[key][0]}~{PHASE_LIMITS_MS[key][1]}ms 밖)")
    for reason, count in sorted(skipped.items(), key=lambda kv: -kv[1]):
        print(f"  제외 {count:3d}개: {reason}")
    print(f"저장: {args.out} / {args.summary}")


if __name__ == "__main__":
    main()
