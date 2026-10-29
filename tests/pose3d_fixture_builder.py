"""Deterministic synthetic renderer fixtures, not player observations.

Run from the repository root with ``python -m tests.pose3d_fixture_builder``.
Only test fixtures are written. No inference, credentials, videos or NPZ input.
"""
from pathlib import Path
import hashlib
import json

import numpy as np

from feedback.pose3d import build_pose3d
from tests.test_pose3d_pipeline import capture_data, skeleton


def packet(count, fps, mirrored):
    data = capture_data(count, mirrored)
    data['decoded_pts_s'] = np.arange(count) / fps
    data['fps'] = float(fps)
    for i in range(count):
        phase = i / max(1, count - 1)
        yaw = .12 + .85 * phase
        c, s = np.cos(yaw), np.sin(yaw)
        rotation = np.asarray([[c, 0, s], [0, 1, 0], [-s, 0, c]])
        data['world_raw'][i] = np.round(data['world_raw'][i] @ rotation.T, 8)
        # Each heel/toe pair has an independent synthetic direction.
        for side in (0, 1):
            ankle = data['world_raw'][i, 10 + side]
            foot_yaw = yaw + (-.35 if side == 0 else .45)
            forward = np.asarray([np.sin(foot_yaw), 0, np.cos(foot_yaw)])
            heel = ankle + np.asarray([0, .01, 0]) - .03 * forward
            data['foot_world_raw'][i, side] = np.round(heel, 8)
            data['foot_world_raw'][i, 2 + side] = np.round(heel + .15 * forward, 8)
    identity = 'synthetic-left60' if mirrored else 'synthetic-right30'
    result = build_pose3d(
        skeleton(data), analysis_id=identity, user_id='synthetic-owner',
        source_sha256=hashlib.sha256(identity.encode()).hexdigest(),
    )
    result['title'] = 'Synthetic geometry test; not a measured swing'
    result['source_provenance']['fixture'] = 'deterministic synthetic coordinates'
    return result


def main():
    destination = Path(__file__).resolve().parents[1] / 'frontend/test/fixtures'
    destination.mkdir(parents=True, exist_ok=True)
    for count, fps, mirrored in ((100, 60, True), (27, 30, False)):
        data = packet(count, fps, mirrored)
        path = destination / (data['id'].replace('-', '_', 1) + '.json')
        path.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False,
                                   separators=(',', ':')) + '\n', encoding='utf-8')
        print(path.name, path.stat().st_size)


if __name__ == '__main__':
    main()
