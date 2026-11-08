"""다음에 라벨링할 영상 100개(묶음 하나)를 고른다.

라벨링 도구(scripts/label_server.py)는 data/label_priority.txt 의 영상을 먼저 보여준다.
목록이 길면 우선순위가 의미가 없어서, 한 번에 한 묶음만 이 파일에 넣는다.
묶음을 다 하면 다시 실행해 다음 묶음을 만든다 (이미 라벨링한 영상은 빠진다).

고르는 기준
    필수   앞발 들기가 영상에 남아 있다 (규칙이나 LSTM 이 찾았고, 착지 0.4초 이상 전부터 찍혔다)
    점수   LSTM 이 헷갈리는 영상을 먼저: 규칙과 LSTM 이 다른 프레임을 고르거나, LSTM 확률이 낮다
           지금 기준 모델에서 빠지는 영상(이벤트 순서 어긋남, 구간 길이 이상)에 가산점
    분산   한 묶음에 같은 선수는 최대 2개. 라벨이 적은 선수를 먼저
    제외   이미 라벨링한 영상, 관절 결측이 많은 영상, 시험용 선수의 영상(학습에 쓰지 않으므로)

사용법:
    python scripts/make_label_batch.py              # 다음 100개
    python scripts/make_label_batch.py --size 50
    -> data/label_priority.txt          라벨링 도구가 먼저 보여줄 순서
       data/label_batches/batch_NN.csv  영상별 점수와 이유
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feedback.event_lstm import EVENT_KEYS, decode_events, from_model_frame, load_event_model  # noqa: E402
from feedback.events import detect_events  # noqa: E402
from scripts.build_reference_model import MAX_NAN_RATIO, PHASE_LIMITS_MS, PHASES  # noqa: E402
from scripts.make_event_test_split import player_of  # noqa: E402

MIN_LIFT_LEAD_MS = 400  # 착지보다 이만큼 이전부터 찍혀 있어야 앞발 들기가 남아 있다고 본다
MAX_PER_PLAYER = 2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=100)
    parser.add_argument("--labels", default="data/labels.csv")
    parser.add_argument("--skeleton-dir", default="data/skeletons")
    parser.add_argument("--split", default="data/event_test_split.json")
    parser.add_argument("--out", default="data/label_priority.txt")
    parser.add_argument("--batch-dir", default="data/label_batches")
    args = parser.parse_args()

    model = load_event_model()
    if model is None:
        raise SystemExit("LSTM 이벤트 모델(feedback/event_lstm.npz)이 없습니다. scripts/train_event_lstm.py 를 먼저 실행하세요.")
    labels = list(csv.DictReader(Path(args.labels).open(encoding="utf-8-sig")))
    labeled = {unicodedata.normalize("NFC", r["video_id"]) for r in labels}
    labels_per_player = Counter(player_of(v) for v in labeled)
    test_players = set(json.loads(Path(args.split).read_text(encoding="utf-8"))["test_players"])

    candidates, skipped = [], Counter()
    for path in sorted(Path(args.skeleton_dir).glob("*.npz")):
        data = np.load(path, allow_pickle=True)
        meta = json.loads(str(data["meta_json"]))
        vid = unicodedata.normalize("NFC", meta["video_id"])
        if vid in labeled:
            continue
        if player_of(vid) in test_players:
            skipped["시험용 선수"] += 1
            continue
        if (~np.isfinite(data["landmarks"].astype(float)).all(axis=(1, 2))).mean() > MAX_NAN_RATIO:
            skipped["관절 결측 많음"] += 1
            continue
        pixel, fps = data["landmarks_pixel"].astype(float), float(meta["fps"])

        rule = detect_events(pixel, fps, use_event_model=False).as_dict()
        prob = model.probabilities(pixel, fps)
        raw = decode_events(prob, present_threshold=model.present_threshold)
        lstm = {k: (None if v is None else from_model_frame(v, fps)) for k, v in raw.items()}

        plant = lstm["foot_plant"] if lstm["foot_plant"] is not None else rule["foot_plant"]
        has_lift = rule["foot_lift"] is not None or lstm["foot_lift"] is not None
        if plant is None or not has_lift or plant / fps * 1000 < MIN_LIFT_LEAD_MS:
            skipped["앞발 들기 없음(앞부분 잘림)"] += 1
            continue

        reasons, score = [], 0.0
        for key in ("foot_lift", "foot_plant", "swing_start", "impact", "follow_end"):
            a, b = rule[key], lstm[key]
            if a is not None and b is not None and abs(a - b) > 2:
                gap = min(abs(a - b), 10)
                score += gap / 2
                reasons.append(f"{key} 규칙/LSTM {abs(a - b)}프레임 차이")
            if raw[key] is not None:
                confidence = float(prob[raw[key], EVENT_KEYS.index(key)])
                if confidence < 0.5:
                    score += (0.5 - confidence) * 6
                    reasons.append(f"{key} LSTM 확신 낮음({confidence:.2f})")

        # 지금(규칙+LSTM) 검출로 기준 모델에서 빠지는지
        events = detect_events(pixel, fps).as_dict()
        order = [events[k] for k in ("foot_lift", "foot_plant", "swing_start", "impact", "follow_end") if events[k] is not None]
        if events["impact"] is None or events["swing_start"] is None or any(b < a for a, b in zip(order, order[1:])):
            score += 5
            reasons.append("기준 모델에서 빠짐(이벤트 순서/미검출)")
        else:
            for key, _, start_key, end_key in PHASES:
                s, e = events[start_key], events[end_key]
                if s is not None and e is not None:
                    low, high = PHASE_LIMITS_MS[key]
                    if not low <= (e - s) / fps * 1000 <= high:
                        score += 2
                        reasons.append(f"{key} 구간 길이 이상")

        candidates.append({"video_id": vid, "player": player_of(vid), "score": round(score, 2),
                           "reason": "; ".join(reasons) or "검출 안정 (학습량 늘리기용)"})

    # 점수 순으로 보되, 같은 선수는 묶음당 MAX_PER_PLAYER 개까지, 라벨 적은 선수 먼저
    candidates.sort(key=lambda c: (-c["score"], labels_per_player[c["player"]], c["video_id"]))
    picked, per_player = [], Counter()
    for c in candidates:
        if per_player[c["player"]] >= MAX_PER_PLAYER:
            continue
        picked.append(c)
        per_player[c["player"]] += 1
        if len(picked) >= args.size:
            break

    batch_dir = Path(args.batch_dir)
    batch_dir.mkdir(parents=True, exist_ok=True)
    number = len(list(batch_dir.glob("batch_*.csv"))) + 1
    batch_path = batch_dir / f"batch_{number:02d}.csv"
    with batch_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["rank", "video_id", "player", "score", "reason"])
        writer.writeheader()
        for rank, c in enumerate(picked, 1):
            writer.writerow({"rank": rank, **c})
    Path(args.out).write_text("\n".join(c["video_id"] for c in picked) + "\n", encoding="utf-8")

    print(f"라벨 {len(labeled)}개 / 후보 {len(candidates)}개 (앞발 들기가 남아 있는 미라벨 영상)")
    for reason, count in skipped.most_common():
        print(f"  제외 {count:3d}개: {reason}")
    print(f"묶음 {number}: {len(picked)}개, 선수 {len(per_player)}명 -> {args.out}, {batch_path}")
    unstable = sum(1 for c in picked if c["score"] > 0)
    print(f"  LSTM 이 헷갈리거나 기준 모델에서 빠지는 영상 {unstable}개, 나머지는 학습량 늘리기용")


if __name__ == "__main__":
    main()
