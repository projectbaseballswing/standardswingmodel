"""LSTM 이벤트 판별 모델을 학습하고, 고정된 시험용 라벨로 규칙 감지기와 비교한다.

1. 사전 학습: 라벨이 없는 영상에서 규칙 감지기가 찾은 이벤트를 임시 정답으로 쓴다.
2. 미세 조정: 사람 라벨로 다시 학습한다.
3. 검증: 학습에 쓰지 않은 선수(검증용)로 이벤트마다 규칙 감지기와 비교해, LSTM 이 나은 이벤트만 쓰도록 정한다.
4. 시험: data/event_test_split.json 의 시험용 라벨로 최종 성적을 낸다. 시험용 선수의 영상은 1~3 에 전혀 쓰지 않는다.

가중치는 NumPy 로 계산할 수 있게 feedback/event_lstm.npz 로 저장한다 (API 서버에는 PyTorch 가 없다).

사용법:
    python scripts/train_event_lstm.py
    python scripts/train_event_lstm.py --no-save      # 성적만 보기
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feedback.event_lstm import (  # noqa: E402
    DEFAULT_EVENT_MODEL_PATH,
    EVENT_KEYS,
    EventModel,
    decode_events,
    from_model_frame,
    sequence_features,
    to_model_frame,
)
from feedback.events import detect_events  # noqa: E402
from scripts.make_event_test_split import player_of  # noqa: E402

SIGMA = 1.0  # 정답 프레임 주변 확률 분포 폭 (모델 프레임 단위)
POS_WEIGHT = 8.0  # 이벤트 프레임은 전체의 몇 % 뿐이라 양성 쪽 손실을 키운다


def num(value):
    return int(value) if value not in (None, "") else None


class EventLSTM(nn.Module):
    def __init__(self, input_dim: int, hidden: int, layers: int, dropout: float):
        super().__init__()
        self.lstm = nn.LSTM(input_dim, hidden, num_layers=layers, batch_first=True, bidirectional=True,
                            dropout=dropout if layers > 1 else 0.0)
        self.drop = nn.Dropout(dropout)
        self.head = nn.Linear(hidden * 2, len(EVENT_KEYS))

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.head(self.drop(out))


def target_of(events: dict, length: int, fps: float, human: bool):
    """(T', 5) 목표 확률과 (5,) 마스크. 사람 라벨에서 빈 이벤트는 '영상에 없음'(전부 0),
    규칙 감지 결과에서 None 은 '모름'(손실에서 뺌)."""
    target = np.zeros((length, len(EVENT_KEYS)), dtype=np.float32)
    mask = np.ones(len(EVENT_KEYS), dtype=np.float32)
    t = np.arange(length)
    for i, key in enumerate(EVENT_KEYS):
        frame = events.get(key)
        if frame is None:
            mask[i] = 1.0 if human else 0.0
            continue
        center = to_model_frame(frame, fps)
        target[:, i] = np.exp(-((t - center) ** 2) / (2 * SIGMA ** 2))
    return target, mask


def load_items(labels_path: Path, skeleton_dir: Path, test_players: set, max_nan: float = 0.3):
    labels = {unicodedata.normalize("NFC", r["video_id"]): r
              for r in csv.DictReader(labels_path.open(encoding="utf-8-sig"))}
    items = []
    for path in sorted(skeleton_dir.glob("*.npz")):
        data = np.load(path, allow_pickle=True)
        meta = json.loads(str(data["meta_json"]))
        vid = unicodedata.normalize("NFC", meta["video_id"])
        pixel = data["landmarks_pixel"].astype(float)
        if (~np.isfinite(data["landmarks"].astype(float)).all(axis=(1, 2))).mean() > max_nan:
            continue
        fps = float(meta["fps"])
        label = labels.get(vid)
        item = {"id": vid, "player": player_of(vid), "fps": fps, "pixel": pixel,
                "x": sequence_features(pixel, fps), "label": label}
        clip_start = num(label.get("clip_start")) if label else None
        clip_end = num(label.get("clip_end")) if label else None
        item["clip"] = (clip_start or 0, clip_end)
        rule = detect_events(pixel, fps, clip_start=clip_start or 0, clip_end=clip_end, use_event_model=False).as_dict()
        item["rule"] = {k: rule[k] for k in EVENT_KEYS}
        if label:
            item["human"] = {k: num(label.get(k)) for k in EVENT_KEYS}
        item["test"] = item["player"] in test_players
        items.append(item)
    return items


def crop(x, target, clip):
    """clip 구간만 남긴다 (라벨러가 쓸 구간을 정한 영상)."""
    start, end = clip
    s = int(np.floor(start))
    e = len(x) if end is None else min(len(x), int(np.ceil(end)) + 1)
    return x[s:e], target[s:e], s


def batches(samples, batch_size, train, rng):
    order = list(range(len(samples)))
    if train:
        rng.shuffle(order)
    for i in range(0, len(order), batch_size):
        chunk = [samples[j] for j in order[i:i + batch_size]]
        xs, ts, ms = [], [], []
        for x, target, mask in chunk:
            if train and len(x) > 40 and rng.random() < 0.5:
                # 앞부분을 잘라 '영상이 늦게 시작한' 경우를 흉내 낸다. 잘려 나간 이벤트는 정답에서도 사라진다.
                cut = rng.randrange(0, len(x) // 3)
                x, target = x[cut:], target[cut:]
            xs.append(x); ts.append(target); ms.append(mask)
        T = max(len(x) for x in xs)
        X = np.zeros((len(xs), T, xs[0].shape[1]), np.float32)
        Y = np.zeros((len(xs), T, len(EVENT_KEYS)), np.float32)
        M = np.zeros((len(xs), T, len(EVENT_KEYS)), np.float32)
        for k, (x, target, mask) in enumerate(zip(xs, ts, ms)):
            X[k, :len(x)], Y[k, :len(x)] = x, target
            M[k, :len(x)] = mask
        yield torch.from_numpy(X), torch.from_numpy(Y), torch.from_numpy(M)


def train(model, samples, epochs, lr, rng, device, label=""):
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    loss_fn = nn.BCEWithLogitsLoss(reduction="none", pos_weight=torch.full((len(EVENT_KEYS),), POS_WEIGHT, device=device))
    for epoch in range(epochs):
        model.train()
        total, count = 0.0, 0
        for X, Y, M in batches(samples, 16, True, rng):
            X, Y, M = X.to(device), Y.to(device), M.to(device)
            loss = (loss_fn(model(X), Y) * M).sum() / M.sum().clamp(min=1)
            opt.zero_grad(); loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            total += float(loss.detach()) * len(X); count += len(X)
        if (epoch + 1) % 10 == 0 or epoch == epochs - 1:
            print(f"  {label} epoch {epoch + 1:3d} loss {total / max(count, 1):.4f}", flush=True)


def export(model, mean, std, layers, use_events, threshold) -> dict:
    payload = {f"w_{k}": v.detach().cpu().numpy() for k, v in model.lstm.state_dict().items()}
    payload["w_head_weight"] = model.head.weight.detach().cpu().numpy()
    payload["w_head_bias"] = model.head.bias.detach().cpu().numpy()
    payload.update(feature_mean=mean, feature_std=std, num_layers=np.asarray(layers),
                   use_events=np.asarray(use_events), present_threshold=np.asarray(threshold))
    return payload


def numpy_model(payload) -> EventModel:
    return EventModel(
        weights={k[2:]: np.asarray(v, dtype=np.float64) for k, v in payload.items() if k.startswith("w_")},
        mean=payload["feature_mean"], std=payload["feature_std"], num_layers=int(payload["num_layers"]),
        use_events=[str(k) for k in payload["use_events"]], present_threshold=float(payload["present_threshold"]),
    )


def predict_torch(model, item, mean, std, threshold, device):
    """학습 중 평가용. NumPy 계산과 같은 결과를 더 빨리 낸다."""
    model.eval()
    with torch.no_grad():
        x = torch.from_numpy(((item["x"] - mean) / std)[None].astype(np.float32)).to(device)
        prob = torch.sigmoid(model(x))[0].cpu().numpy()
    start, end = item["clip"]
    s = int(np.floor(to_model_frame(start, item["fps"])))
    e = None if end is None else int(np.ceil(to_model_frame(end, item["fps"])))
    picked = decode_events(prob, s, e, threshold)
    n = len(item["pixel"])
    return {k: (None if v is None else min(n - 1, from_model_frame(v, item["fps"]))) for k, v in picked.items()}


def score(items, predictions):
    """이벤트별 (±2 이내 비율, 평균 절대오차, 정답 수). 사람 라벨이 있는 이벤트만 센다.
    예측이 없으면 오차 15 프레임으로 친다."""
    out = {}
    for key in EVENT_KEYS:
        errors = []
        for item, pred in zip(items, predictions):
            truth = item["human"].get(key)
            if truth is None:
                continue
            errors.append(15 if pred.get(key) is None else min(15, abs(pred[key] - truth)))
        errors = np.asarray(errors, dtype=float)
        out[key] = (float(np.mean(errors <= 2)) if len(errors) else float("nan"),
                    float(errors.mean()) if len(errors) else float("nan"), len(errors))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", default="data/labels.csv")
    parser.add_argument("--skeleton-dir", default="data/skeletons")
    parser.add_argument("--split", default="data/event_test_split.json")
    parser.add_argument("--out", default=str(DEFAULT_EVENT_MODEL_PATH))
    parser.add_argument("--hidden", type=int, default=64)
    parser.add_argument("--layers", type=int, default=2)
    parser.add_argument("--dropout", type=float, default=0.3)
    parser.add_argument("--pretrain-epochs", type=int, default=30)
    parser.add_argument("--finetune-epochs", type=int, default=60)
    parser.add_argument("--val-ratio", type=float, default=0.2, help="학습용 라벨 중 검증에 쓸 선수 비율")
    parser.add_argument("--threshold", type=float, default=0.2, help="앞발 들기/착지가 '있다'고 볼 최소 확률")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    rng = random.Random(args.seed)
    device = "cpu"  # 짧은 시퀀스라 CPU 가 충분히 빠르고 결과가 재현된다

    split = json.loads(Path(args.split).read_text(encoding="utf-8"))
    test_players = set(split["test_players"])
    test_videos = set(split["test_videos"])
    started = time.time()
    items = load_items(Path(args.labels), Path(args.skeleton_dir), test_players)
    print(f"영상 {len(items)}개 불러옴 ({time.time() - started:.0f}초)")

    pool = [it for it in items if not it["test"]]
    labeled_players = sorted({it["player"] for it in pool if it["label"]})
    rng.shuffle(labeled_players)
    val_players = set(labeled_players[: max(1, round(len(labeled_players) * args.val_ratio))])
    val = [it for it in pool if it["label"] and it["player"] in val_players]
    train_labeled = [it for it in pool if it["label"] and it["player"] not in val_players]
    train_pseudo = [it for it in pool if not it["label"] and it["player"] not in val_players]
    test = [it for it in items if it["id"] in test_videos]
    print(f"사전 학습(규칙 결과) {len(train_pseudo)}개 / 미세 조정(사람 라벨) {len(train_labeled)}개 / "
          f"검증 {len(val)}개 (선수 {len(val_players)}명) / 시험 {len(test)}개")

    feats = np.concatenate([it["x"] for it in train_pseudo + train_labeled])
    mean, std = feats.mean(axis=0), feats.std(axis=0) + 1e-6

    def samples(group, human):
        out = []
        for it in group:
            events = it["human"] if human else it["rule"]
            target, mask = target_of(events, len(it["x"]), it["fps"], human)
            clip = (to_model_frame(it["clip"][0], it["fps"]),
                    None if it["clip"][1] is None else to_model_frame(it["clip"][1], it["fps"]))
            x, target, _ = crop((it["x"] - mean) / std, target, clip)
            out.append((x.astype(np.float32), target, mask))
        return out

    model = EventLSTM(len(mean), args.hidden, args.layers, args.dropout).to(device)
    if args.pretrain_epochs:
        print("[사전 학습: 규칙 감지 결과]")
        train(model, samples(train_pseudo, False), args.pretrain_epochs, 2e-3, rng, device, "pre")
    print("[미세 조정: 사람 라벨]")
    train(model, samples(train_labeled, True), args.finetune_epochs, 5e-4, rng, device, "fine")

    # 검증: 이벤트마다 규칙 감지기와 비교해 쓸 이벤트를 고른다
    val_lstm = score(val, [predict_torch(model, it, mean, std, args.threshold, device) for it in val])
    val_rule = score(val, [it["rule"] for it in val])
    # 검증 표본이 작아 동점이 자주 난다. 동점이면 LSTM 을 쓴다 (시드 3개 시험에서 LSTM 이 같거나 나았다).
    use_events = [k for k in EVENT_KEYS if val_lstm[k][0] >= val_rule[k][0]]
    print("\n[검증 (선수 %d명, 스윙 %d개)]  ±2프레임 이내 비율" % (len(val_players), len(val)))
    for k in EVENT_KEYS:
        print(f"  {k:12s} 규칙 {val_rule[k][0]:4.0%}  LSTM {val_lstm[k][0]:4.0%}  (n={val_lstm[k][2]})"
              + ("  -> LSTM 사용" if k in use_events else ""))

    payload = export(model, mean.astype(np.float32), std.astype(np.float32), args.layers, use_events, args.threshold)
    numpy_version = numpy_model(payload)

    # NumPy 계산이 PyTorch 와 같은지 확인
    check = test[0]
    torch_pred = predict_torch(model, check, mean, std, args.threshold, device)
    numpy_pred = numpy_version.predict(check["pixel"], check["fps"], *check["clip"])
    assert torch_pred == numpy_pred, (torch_pred, numpy_pred)

    test_lstm_raw = [numpy_version.predict(it["pixel"], it["fps"], *it["clip"]) for it in test]
    test_hybrid = [{k: (p[k] if k in use_events else it["rule"][k]) for k in EVENT_KEYS}
                   for it, p in zip(test, test_lstm_raw)]
    results = {"규칙": score(test, [it["rule"] for it in test]),
               "LSTM 단독": score(test, test_lstm_raw),
               "규칙+LSTM": score(test, test_hybrid)}
    print("\n[시험 (선수 %d명, 스윙 %d개, 학습에 안 쓴 선수)]  ±2프레임 이내 비율 (평균 절대오차)" % (len(test_players), len(test)))
    print("%-12s" % "" + "".join(f"{k:>18s}" for k in EVENT_KEYS))
    for name, res in results.items():
        print("%-12s" % name + "".join(f"{res[k][0]:>10.0%} ({res[k][1]:4.1f})" for k in EVENT_KEYS))

    if not args.no_save:
        payload["test_summary_json"] = np.asarray(json.dumps(
            {name: {k: [round(v[0], 3), round(v[1], 2), v[2]] for k, v in res.items()} for name, res in results.items()},
            ensure_ascii=False))
        payload["labels_used"] = np.asarray(len(train_labeled))
        np.savez_compressed(args.out, **payload)
        print("\n저장:", args.out)


if __name__ == "__main__":
    main()
