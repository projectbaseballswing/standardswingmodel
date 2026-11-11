"""VAE 개선 자세 모델을 학습하고 검증한다 (feedback/pose_vae.py, docs/pose-vae.md).

데이터   기준 모델과 같은 프로 스윙, 같은 이벤트. 구간마다 20 시점으로 맞춘 뼈 11개 방향 (user_motion 과 같은 전처리)
검증     학습에 쓰지 않은 선수(검증용)의 스윙으로
         1. 스타일 보존: 개선 자세가 그 선수 자신의 스윙에 얼마나 가까운가 (대표 자세와 비교)
         2. 실수 복원: 프로 스윙에 실수를 일부러 넣고, 개선 자세가 원래 스윙으로 되돌리는가
            (실수를 넣은 뼈는 되돌리고, 넣지 않은 뼈는 그대로 두는가)
         3. 단순 계산(프로 범위를 벗어난 뼈만 범위 안으로 당기기)과 비교

사용법:
    python scripts/train_pose_vae.py
    python scripts/train_pose_vae.py --beta 0.5 --no-save
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feedback.pose_vae import (  # noqa: E402
    DEFAULT_POSE_VAE_PATH, N_BONES, PHASE_KEYS, SEQ_LEN, VAE_VERSION, PoseVAE, angle_deg, model_inputs,
    phase_directions, time_inputs,
)
from feedback.reference_motion import BONE_NAMES, PHASE_POINTS, bone_vectors, load_reference_motion, user_motion  # noqa: E402
from scripts.build_reference_model import load_labels, phase_windows, swing_events  # noqa: E402
from scripts.make_event_test_split import player_of  # noqa: E402

B = {name: i for i, name in enumerate(BONE_NAMES)}
P = {key: i * PHASE_POINTS for i, key in enumerate(PHASE_KEYS)}  # 구간 첫 시점 번호


# ----------------------------------------------------------------------
# 데이터
# ----------------------------------------------------------------------
def collect(skeleton_dir: Path, labels: dict) -> list[dict]:
    items = []
    for path in sorted(skeleton_dir.glob("*.npz")):
        data = np.load(path, allow_pickle=True)
        meta = json.loads(str(data["meta_json"]))
        events, _ = swing_events(data, labels)
        if events is None:
            continue
        fps = float(meta["fps"])
        ok = {key for key, _, _, good in phase_windows(events, fps) if good}
        motion = user_motion(data["landmarks_pixel"].astype(float), fps, events)
        phases = {k: v for k, v in motion["phases"].items() if k in ok}
        dirs, mask = phase_directions(phases)
        if mask.sum() < 2 * PHASE_POINTS:
            continue
        items.append({"id": meta["video_id"], "player": player_of(meta["video_id"]), "dirs": dirs, "mask": mask})
    return items


# ----------------------------------------------------------------------
# 모델
# ----------------------------------------------------------------------
class SeqVAE(nn.Module):
    def __init__(self, hidden: int, latent: int):
        super().__init__()
        in_dim = N_BONES * 3 + time_inputs().shape[1] + 1
        self.enc = nn.LSTM(in_dim, hidden, batch_first=True, bidirectional=True)
        self.mu = nn.Linear(2 * hidden, latent)
        self.logvar = nn.Linear(2 * hidden, latent)
        self.dec = nn.LSTM(latent + time_inputs().shape[1], hidden, batch_first=True, bidirectional=True)
        self.out = nn.Linear(2 * hidden, N_BONES * 3)
        self.register_buffer("time", torch.from_numpy(time_inputs()).float())

    def encode(self, x, mask):
        h, _ = self.enc(x)
        pooled = (h * mask[..., None]).sum(1) / mask.sum(1, keepdim=True).clamp(min=1)
        return self.mu(pooled), self.logvar(pooled)

    def decode(self, z):
        t = self.time[None].expand(len(z), -1, -1)
        h, _ = self.dec(torch.cat([z[:, None].expand(-1, SEQ_LEN, -1), t], dim=-1))
        out = self.out(h).view(len(z), SEQ_LEN, N_BONES, 3)
        return out / out.norm(dim=-1, keepdim=True).clamp(min=1e-6)


def to_tensors(items, rng: random.Random, augment: bool):
    xs, ds, ms = [], [], []
    for it in items:
        mask = it["mask"].copy()
        if augment and rng.random() < 0.25 and mask[:PHASE_POINTS].all():
            mask[:PHASE_POINTS] = False  # 스트라이드가 안 찍힌 영상도 다룰 수 있게
        xs.append(model_inputs(it["dirs"], mask))
        ds.append(it["dirs"])
        ms.append(it["mask"] if not augment else mask)
    return (torch.tensor(np.stack(xs), dtype=torch.float32), torch.tensor(np.stack(ds), dtype=torch.float32),
            torch.tensor(np.stack(ms), dtype=torch.float32))


def train(model, items, epochs, beta, lr, rng):
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    for epoch in range(epochs):
        model.train()
        order = list(range(len(items)))
        rng.shuffle(order)
        total = 0.0
        for i in range(0, len(order), 32):
            x, d, m = to_tensors([items[j] for j in order[i:i + 32]], rng, augment=True)
            # 학습 입력에도 작은 흔들림을 넣는다 (관절 좌표 잡음에 덜 민감하게)
            x[..., :N_BONES * 3] += 0.03 * torch.randn_like(x[..., :N_BONES * 3]) * m[..., None]
            mu, logvar = model.encode(x, m)
            z = mu + torch.randn_like(mu) * (0.5 * logvar).exp()
            recon = model.decode(z)
            # 정답은 실제로 있는 구간 전부 (입력에서 일부러 가린 구간도 맞히게 한다)
            full = torch.tensor(np.stack([items[j]["mask"] for j in order[i:i + 32]]), dtype=torch.float32)
            rec = (((recon - d) ** 2).sum(-1).sum(-1) * full).sum(1) / full.sum(1).clamp(min=1)
            kl = -0.5 * (1 + logvar - mu ** 2 - logvar.exp()).sum(1)
            loss = (rec + beta * kl / SEQ_LEN).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += loss.item() * len(x)
        if (epoch + 1) % 50 == 0:
            print(f"  epoch {epoch + 1:4d} loss {total / len(items):.4f}", flush=True)


def export(model, latent, hidden, beta, swings, players) -> dict:
    payload = {f"w_{k}": v.detach().cpu().numpy().astype(np.float32) for k, v in model.state_dict().items()
               if not k.startswith("logvar") and k != "time"}
    payload["metadata_json"] = np.asarray(json.dumps({
        "version": VAE_VERSION, "built_on": date.today().isoformat(), "latent": latent, "hidden": hidden,
        "beta": beta, "swings_used": swings, "players_used": players, "bones": BONE_NAMES, "phases": PHASE_KEYS,
    }, ensure_ascii=False))
    return payload


# ----------------------------------------------------------------------
# 검증
# ----------------------------------------------------------------------
def _rotate(vectors: np.ndarray, axis: np.ndarray, degrees: np.ndarray) -> np.ndarray:
    """Rodrigues 회전. vectors (T, 3), degrees (T,)."""
    k = axis / np.linalg.norm(axis)
    th = np.radians(degrees)[:, None]
    return vectors * np.cos(th) + np.cross(k, vectors) * np.sin(th) + k * (vectors @ k)[:, None] * (1 - np.cos(th))


# 일부러 넣는 실수: (이름, [(뼈, 회전축, 각도 부호)], 시작 시점, 끝 시점, 각도)
# 축: z = 화면 평면 안에서 돌리기, y = 몸통 회전 방향
FAULTS = [
    ("앞 무릎 과하게 굽힘", [("lead_thigh", (0, 0, 1), -1), ("lead_shin", (0, 0, 1), 1)], P["transition"], P["swing"] + 19, 25),
    ("상체 앞으로 쏠림", [("spine", (0, 0, 1), -1)], P["transition"] + 10, P["swing"] + 19, 20),
    ("뒷팔꿈치 들림", [("rear_upper_arm", (0, 0, 1), 1)], P["stride"] + 10, P["transition"] + 19, 35),
    ("어깨 일찍 열림", [("shoulders", (0, 1, 0), 1)], P["transition"], P["swing"] + 10, 30),
]


def inject(dirs: np.ndarray, fault) -> tuple[np.ndarray, np.ndarray]:
    _, bones, start, end, size = fault
    out = dirs.copy()
    t = np.arange(SEQ_LEN)
    ramp = np.clip(np.minimum(t - start + 1, end - t + 1) / 4.0, 0, 1)  # 앞뒤 4 시점에 걸쳐 서서히
    touched = np.zeros((SEQ_LEN, N_BONES), dtype=bool)
    for name, axis, sign in bones:
        b = B[name]
        out[:, b] = _rotate(dirs[:, b], np.asarray(axis, float), sign * size * ramp)
        touched[:, b] = ramp > 0.5
    return out, touched


def clamp_to_band(dirs, mask, ref_dirs, spread, k=1.5):
    """단순 계산: 대표 자세에서 k x 퍼짐 보다 멀리 간 뼈만 그 경계까지 당긴다."""
    out = dirs.copy()
    ang = angle_deg(dirs, ref_dirs)
    limit = k * spread
    for t, b in zip(*np.nonzero((ang > limit) & mask[:, None])):
        a, r = dirs[t, b], ref_dirs[t, b]
        axis = np.cross(a, r)
        if np.linalg.norm(axis) < 1e-9:
            continue
        out[t, b] = _rotate(a[None], axis, np.array([ang[t, b] - limit[t, b]]))[0]
    return out


def evaluate(vae: PoseVAE, items: list[dict]) -> dict:
    ref = load_reference_motion()
    ref_dirs = np.zeros((SEQ_LEN, N_BONES, 3))
    spread = np.zeros((SEQ_LEN, N_BONES))
    for p, key in enumerate(PHASE_KEYS):
        v = bone_vectors(np.asarray(ref.phases[key].joints))
        ref_dirs[p * PHASE_POINTS:(p + 1) * PHASE_POINTS] = v / np.linalg.norm(v, axis=-1, keepdims=True)
        spread[p * PHASE_POINTS:(p + 1) * PHASE_POINTS] = np.maximum(np.asarray(ref.phases[key].spread_deg), 5.0)

    result = {}
    style_vae, style_ref = [], []
    for it in items:
        m = it["mask"]
        style_vae.append(angle_deg(vae.improve(it["dirs"], m), it["dirs"])[m].mean())
        style_ref.append(angle_deg(ref_dirs, it["dirs"])[m].mean())
    result["style"] = {"vae_deg": float(np.mean(style_vae)), "reference_deg": float(np.mean(style_ref))}

    for fault in FAULTS:
        rows = {"vae": [], "clamp": []}
        for it in items:
            m = it["mask"]
            faulty, touched = inject(it["dirs"], fault)
            touched &= m[:, None]
            if not touched.any():
                continue
            other = m[:, None] & ~np.isin(np.arange(N_BONES), [B[n] for n, *_ in fault[1]])[None]
            clean_vae = vae.improve(it["dirs"], m)
            for name, fixed, base in [("vae", vae.improve(faulty, m), clean_vae),
                                      ("clamp", clamp_to_band(faulty, m, ref_dirs, spread),
                                       clamp_to_band(it["dirs"], m, ref_dirs, spread))]:
                rows[name].append([
                    angle_deg(faulty, it["dirs"])[touched].mean(),   # 넣은 실수 크기
                    angle_deg(fixed, it["dirs"])[touched].mean(),    # 고친 뒤 원래 스윙과 차이
                    angle_deg(base, it["dirs"])[touched].mean(),     # 실수 없는 스윙을 넣었을 때의 차이 (바닥)
                    angle_deg(fixed, base)[other].mean(),            # 실수를 넣지 않은 뼈가 실수 때문에 바뀐 정도
                ])
        result[fault[0]] = {k: np.mean(v, axis=0).round(2).tolist() for k, v in rows.items()}
    return result


def print_eval(res: dict) -> None:
    s = res["style"]
    print(f"\n[스타일 보존] 실수 없는 프로 스윙을 넣었을 때 원래 스윙과 평균 차이: VAE {s['vae_deg']:.1f}도 "
          f"(모두에게 같은 대표 자세였다면 {s['reference_deg']:.1f}도)")
    print("\n[실수 복원] 넣은 실수 -> 고친 뒤 원래 스윙과 차이 (실수 없을 때 바닥) | 다른 뼈가 덩달아 바뀐 정도  (도)")
    for name, _, *_ in FAULTS:
        line = f"  {name:12s}"
        for method, label in [("vae", "VAE"), ("clamp", "단순 계산")]:
            size, after, floor, other = res[name][method]
            line += f"   {label} {size:4.1f} -> {after:4.1f} ({floor:4.1f}) | {other:3.1f}"
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", default="data/labels.csv")
    parser.add_argument("--skeleton-dir", default="data/skeletons")
    parser.add_argument("--out", default=str(DEFAULT_POSE_VAE_PATH))
    parser.add_argument("--latent", type=int, default=16)
    parser.add_argument("--hidden", type=int, default=64)
    parser.add_argument("--beta", type=float, default=1.0, help="KL 가중치. 클수록 더 '프로다운' 쪽으로 강하게 고친다")
    parser.add_argument("--epochs", type=int, default=300)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--final", action="store_true", help="검증 후 검증용 선수까지 포함해 다시 학습해서 저장")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    rng = random.Random(args.seed)
    started = time.time()
    items = collect(Path(args.skeleton_dir), load_labels(Path(args.labels)))
    players = sorted({it["player"] for it in items})
    rng.shuffle(players)
    val_players = set(players[: max(1, round(len(players) * args.val_ratio))])
    train_items = [it for it in items if it["player"] not in val_players]
    val_items = [it for it in items if it["player"] in val_players]
    print(f"스윙 {len(items)}개 ({time.time() - started:.0f}초) / 학습 {len(train_items)} / 검증 {len(val_items)} "
          f"(선수 {len(val_players)}명)")

    model = SeqVAE(args.hidden, args.latent)
    train(model, train_items, args.epochs, args.beta, 2e-3, rng)
    vae = PoseVAE(weights={k[2:]: v.astype(np.float64) for k, v in
                           export(model, args.latent, args.hidden, args.beta, 0, 0).items() if k.startswith("w_")},
                  metadata={})
    res = evaluate(vae, val_items)
    print_eval(res)

    # NumPy 계산이 PyTorch 와 같은지 확인
    check = val_items[0]
    with torch.no_grad():
        x = torch.tensor(model_inputs(check["dirs"], check["mask"])[None], dtype=torch.float32)
        mu, _ = model.encode(x, torch.tensor(check["mask"][None], dtype=torch.float32))
        torch_out = model.decode(mu)[0].numpy()
    assert np.allclose(torch_out, vae.improve(check["dirs"], check["mask"]), atol=1e-4)

    used = train_items
    if args.final:
        print("\n[최종 학습: 검증용 선수 포함]")
        model = SeqVAE(args.hidden, args.latent)
        train(model, items, args.epochs, args.beta, 2e-3, rng)
        used = items
    if not args.no_save:
        payload = export(model, args.latent, args.hidden, args.beta, len(used), len({it["player"] for it in used}))
        payload["validation_json"] = np.asarray(json.dumps(res, ensure_ascii=False))
        np.savez_compressed(args.out, **payload)
        print("\n저장:", args.out)


if __name__ == "__main__":
    main()
