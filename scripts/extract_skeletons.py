"""기준 영상 전체에서 프레임별 스켈레톤을 추출해 저장한다.

기존 .npy 는 임팩트 기준 80프레임으로 이미 잘려 있고 앞부분이 복사 프레임으로 채워져 있어서,
이벤트(로딩 시작 / 착지 / 스윙 시작 / 임팩트) 검출에 쓸 수 없다. 이 스크립트는 자르기 전
실제 프레임 데이터를 남긴다.

사용법:
    python scripts/extract_skeletons.py --video-dir data/videos --out-dir data/skeletons

저장 형식: data/skeletons/<영상이름>.npz
    landmarks        (T, 12, 3)  몸 기준 좌표계로 정규화된 관절 좌표
    landmarks_pixel  (T, 12, 3)  원본 프레임 좌표
    visibility       (T, 12)     관절별 검출 신뢰도
    meta_json                    fps, 프레임 수, 좌우타, 기존 방식의 임팩트 프레임 등

이어서 실행할 수 있다(이미 저장된 영상은 건너뜀).
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feedback.pipeline import PipelineError, SwingPipeline  # noqa: E402
from feedback.reference import PROJECT_ROOT  # noqa: E402

VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}

logging.basicConfig(level=logging.WARNING, format="%(message)s")


def load_handedness(path: Path) -> dict:
    """metadata.json 의 좌우타 정보. 파일명은 NFC 로 정규화해서 비교한다."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return {
        unicodedata.normalize("NFC", Path(name).stem): value.get("handedness", "right")
        for name, value in data.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="영상에서 프레임별 스켈레톤을 추출해 저장합니다.")
    parser.add_argument("--video-dir", default="data/videos")
    parser.add_argument("--out-dir", default="data/skeletons")
    parser.add_argument("--metadata", default="metadata.json")
    parser.add_argument("--summary", default="data/skeletons_summary.csv")
    parser.add_argument("--limit", type=int, default=0, help="앞에서 N개만 처리 (0=전체)")
    args = parser.parse_args()

    video_dir, out_dir = Path(args.video_dir), Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    handedness = load_handedness(PROJECT_ROOT / args.metadata)

    videos = sorted(p for p in video_dir.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES)
    if args.limit:
        videos = videos[: args.limit]
    print(f"영상 {len(videos)}개 / 좌우타 정보 {len(handedness)}개")

    pipeline = SwingPipeline(target_fps=None)  # 원본 fps 그대로 저장한다
    rows, started, done, skipped, failed = [], time.time(), 0, 0, 0

    for idx, video in enumerate(videos, 1):
        stem = unicodedata.normalize("NFC", video.stem)
        out_path = out_dir / f"{stem}.npz"
        if out_path.exists():
            skipped += 1
            continue

        hand = handedness.get(stem, "right")
        row = {"video_id": stem, "status": "ok", "handedness": hand, "error": ""}
        try:
            result = pipeline.extract_skeleton(str(video), is_left=(hand == "left"))
            n_frames = result.landmarks.shape[0]
            hand_center = (result.landmarks[:, 4, :2] + result.landmarks[:, 5, :2]) / 2
            speeds = np.linalg.norm(np.diff(hand_center, axis=0), axis=1)
            impact_idx = int(np.nanargmax(speeds)) + 1 if len(speeds) else 0

            meta = {
                "video_id": stem,
                "source_file": video.name,
                "handedness": hand,
                "fps": result.fps,
                "n_frames": n_frames,
                "frame_width": result.frame_size[0],
                "frame_height": result.frame_size[1],
                "impact_frame_hand_speed": impact_idx,
                "max_missing_gap": result.max_missing_gap,
            }
            np.savez_compressed(
                out_path,
                landmarks=result.landmarks.astype(np.float32),
                landmarks_pixel=result.landmarks_pixel.astype(np.float32),
                visibility=result.visibility.astype(np.float32),
                meta_json=json.dumps(meta, ensure_ascii=False),
            )
            row.update(
                fps=round(result.fps, 2),
                n_frames=n_frames,
                duration_s=round(n_frames / result.fps, 2) if result.fps else "",
                impact_frame=impact_idx,
                frames_before_impact=impact_idx,
                frames_after_impact=n_frames - impact_idx,
                mean_visibility=round(float(np.nanmean(result.visibility)), 3),
                max_missing_gap=result.max_missing_gap,
            )
            done += 1
        except PipelineError as exc:
            row.update(status="failed", error=f"{exc.code}: {exc.message}")
            failed += 1
        except Exception as exc:  # 한 영상이 실패해도 전체는 계속 진행
            row.update(status="failed", error=f"INTERNAL: {exc}")
            failed += 1

        rows.append(row)
        elapsed = time.time() - started
        per_video = elapsed / max(done + failed, 1)
        remaining = (len(videos) - idx) * per_video
        print(
            f"[{idx}/{len(videos)}] {stem} {row['status']} "
            f"| 완료 {done} 실패 {failed} 건너뜀 {skipped} "
            f"| 남은 시간 약 {remaining / 60:.0f}분",
            flush=True,
        )

    if rows:
        fieldnames = [
            "video_id", "status", "handedness", "fps", "n_frames", "duration_s",
            "impact_frame", "frames_before_impact", "frames_after_impact",
            "mean_visibility", "max_missing_gap", "error",
        ]
        summary = Path(args.summary)
        summary.parent.mkdir(parents=True, exist_ok=True)
        write_header = not summary.exists()
        with summary.open("a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerows(rows)
        print(f"요약: {summary}")

    print(f"완료 {done} / 실패 {failed} / 건너뜀 {skipped}")


if __name__ == "__main__":
    main()
