"""이벤트 판별 시험용 라벨을 선수 단위로 골라 고정한다.

앞발 들기가 영상에 남아 있는(라벨이 찍힌) 스윙만 시험용으로 쓴다. 시험용 선수의 다른 스윙은
라벨이 있든 없든 학습에서 뺀다. 같은 선수의 스윙이 학습에 섞이면 그 선수의 습관을 외워서 정확도가 부풀려진다.

한 번 만들면 라벨이 늘어도 다시 만들지 않는다 (같은 시험지로 비교해야 하므로). 이미 있으면 덮어쓰지 않는다.

사용법:
    python scripts/make_event_test_split.py --ratio 0.3
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date
from pathlib import Path


def player_of(video_id: str) -> str:
    """'Kt_10_강백호' -> '강백호'. 팀이 바뀐 선수도 같은 사람으로 묶는다.
    '이외_9' 처럼 선수 이름이 없는 영상은 영상 하나를 한 선수로 본다."""
    parts = video_id.split("_")
    return parts[-1] if len(parts) == 3 else video_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", default="data/labels.csv")
    parser.add_argument("--out", default="data/event_test_split.json")
    parser.add_argument("--ratio", type=float, default=0.3, help="앞발 들기가 있는 라벨 중 시험용 비율")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"{out} 이 이미 있습니다. 시험지는 고정해서 씁니다. 다시 만들려면 파일을 직접 지우세요.")

    rows = list(csv.DictReader(Path(args.labels).open(encoding="utf-8-sig")))
    with_lift = [r for r in rows if r.get("foot_lift")]
    by_player: dict[str, list[str]] = {}
    for r in with_lift:
        by_player.setdefault(player_of(r["video_id"]), []).append(r["video_id"])

    players = sorted(by_player)
    random.Random(args.seed).shuffle(players)
    target = round(len(with_lift) * args.ratio)
    test_players, test_videos = [], []
    for name in players:
        if len(test_videos) >= target:
            break
        test_players.append(name)
        test_videos.extend(by_player[name])

    payload = {
        "created": date.today().isoformat(),
        "rule": "앞발 들기 라벨이 있는 스윙만, 선수 단위로 분리. 시험용 선수의 다른 영상은 학습에서 제외",
        "seed": args.seed,
        "labels_at_creation": len(rows),
        "test_players": sorted(test_players),
        "test_videos": sorted(test_videos),
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"앞발 들기 라벨 {len(with_lift)}개 / 선수 {len(by_player)}명")
    print(f"시험용: 선수 {len(test_players)}명, 스윙 {len(test_videos)}개 -> {out}")


if __name__ == "__main__":
    main()
