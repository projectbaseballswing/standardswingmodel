"""Reusable offline S2 display preprocessing; no inference, API or scoring calls.

The frozen numerical implementation is vendored unchanged. This boundary adds
strict input provenance and duplicate-processing checks. P2 is an input policy,
never inferred from smoothed coordinates. O1/F1/H4 run later in Flutter.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re

import numpy as np

ROOT = Path(__file__).resolve().parent
from .vendor.tools import smoothing as frozen
CONTRACT = 'EXP007-final-display-v1'
COORDINATES = 'source_view_hip_centered_xright_yup_zcamera'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_raw(clip):
    if clip.get('source_oriented') is not True or clip.get('coordinate_convention') != COORDINATES:
        raise ValueError('Explicit source-oriented coordinate contract required; no implicit mirroring')
    if clip.get('handedness') not in ('left', 'right', 'unknown'):
        raise ValueError('Explicit handedness or unknown required; never infer from a filename')
    if type(clip.get('mirrored_input')) is not bool:
        raise ValueError('Input mirroring provenance required')
    smoothing = clip.get('smoothing', {})
    if smoothing.get('condition', 'S0') != 'S0' or smoothing.get('joint_coordinates_modified', False):
        raise ValueError('S2 accepts raw/S0 only; repeated smoothing is forbidden')
    if clip.get('processing', {}).get('smoothing_passes', 0) != 0:
        raise ValueError('Already processed input')
    frames = clip.get('frames', [])
    if not frames or len(frames) != clip.get('frame_count'):
        raise ValueError('Nonempty exact frame count required')
    if any(f.get('feet') is not None for f in frames) and clip.get('foot_joint_names') != [
            'left_heel', 'right_heel', 'left_foot_index', 'right_foot_index']:
        raise ValueError('Explicit heel/toe order required when foot observations exist')
    for i, frame in enumerate(frames):
        if frame.get('index') != i:
            raise ValueError('Contiguous source indices required')
        policy = frame.get('p2')
        if not isinstance(policy, dict):
            raise ValueError('Explicit upstream P2 masks required')
        for key in ('edge_visible', 'joint_warnings'):
            if not isinstance(policy.get(key), list) or len(policy[key]) != 12 or any(type(v) is not bool for v in policy[key]):
                raise ValueError('P2 needs 12 explicit booleans for ' + key)
        if type(policy.get('torso_visible')) is not bool or not isinstance(policy.get('warnings'), list):
            raise ValueError('P2 torso/warning contract required')
    pts = np.asarray([f.get('decoded_pts_s') for f in frames], dtype=float)
    if not np.isfinite(pts).all() or np.any(np.diff(pts) <= 0):
        raise ValueError('Strictly increasing finite decoded PTS required')
    # Validate finite/null XYZ, frame order and coordinate labels even before
    # normalization. The frozen core then performs the same numeric validation.
    candidate = copy.deepcopy(clip)
    for i, frame in enumerate(candidate['frames']):
        frame['timestamp_s'] = float(pts[i] - pts[0])
    frozen.clip_arrays(candidate)


def preprocess(raw):
    """Return independent S0 + S2 clips; preserve inputs, masks and nulls.

    S2 uses +/-67 ms local samples plus whole-clip length reference medians.
    Therefore this is an offline post-analysis operation, not causal streaming.
    """
    validate_raw(raw)
    original = copy.deepcopy(raw)
    if raw.get('temporal_adapter', {}).get('source') == 'decoded_pts_s':
        s0 = copy.deepcopy(raw)
        pts = np.asarray([f['decoded_pts_s'] for f in s0['frames']], float)
        if any(abs(f['timestamp_s'] - float(pts[i] - pts[0])) > 1e-12
               for i, f in enumerate(s0['frames'])):
            raise ValueError('Decoded-PTS adapter metadata disagrees with timestamps')
    else:
        s0 = frozen.adapt_timestamps(raw)
    # A caller may already supply normalized decoded PTS without a smoothing
    # record. Mark the verified raw state explicitly for the Dart boundary;
    # this is provenance only and does not filter or modify coordinates.
    s0['smoothing'] = {**s0.get('smoothing', {}),
        'version': frozen.CONFIG['version'], 'condition': 'S0',
        'joint_coordinates_modified': False, 'raw_missingness_preserved': True,
        'original_p2_masks_preserved': True, 'actual_accuracy': 'not_measured'}
    s2 = frozen.smooth_clip(s0, 'S2')
    s2['smoothing']['config_sha256'] = file_sha(ROOT / 'vendor/config/smoothing.json')
    for a, b in zip(s0['frames'], s2['frames']):
        assert a['p2'] == b['p2'], 'S2 changed upstream P2 masks'
        assert a['timestamp_s'] == b['timestamp_s'], 'S2 changed PTS'
        for key, count in [('positions', 12), ('feet', 4)]:
            aa = frozen.as_points(a.get(key), count)
            bb = frozen.as_points(b.get(key), count)
            assert np.array_equal(np.isfinite(aa).all(-1), np.isfinite(bb).all(-1))
    assert raw == original, 'Preprocessing mutated caller data'
    return s0, s2


def motion_digest(clip):
    return digest({
        'coordinate_convention': clip['coordinate_convention'],
        'source_oriented': clip['source_oriented'],
        'mirrored_input': clip['mirrored_input'],
        'handedness': clip['handedness'],
        'joint_names': clip['joint_names'],
        'frames': [{k: f.get(k) for k in ('index', 'timestamp_s',
                   'decoded_pts_s', 'positions', 'feet', 'p2')}
                   for f in clip['frames']],
    })


def package(raw, binding_id, reference_scale=None):
    if not isinstance(binding_id, str) or not binding_id.strip():
        raise ValueError('Nonempty clip binding ID required')
    s0, s2 = preprocess(raw)
    source_hash = raw.get('source_provenance', {}).get('source_sha256')
    if not isinstance(source_hash, str) or re.fullmatch(r'[a-fA-F0-9]{64}', source_hash) is None:
        raise ValueError('Source SHA256 identity required')
    if reference_scale is not None and (not np.isfinite(reference_scale) or reference_scale <= 0):
        raise ValueError('Reference scale must be finite and positive')
    times = [f['timestamp_s'] for f in s0['frames']]
    last_interval = float(np.median(np.diff(times))) if len(times) > 1 else 1. / raw['fps']
    end = times[-1] + last_interval
    for clip in (s0, s2):
        clip['presentation_end_s'] = end
        clip['display_policy'] = {'id': 'P2', 'provenance': 'Frozen upstream P2 masks; not recomputed after S2'}
        # Device-independent bundles never depend on local source file paths.
        for key in ('original_source_path', 'source_path', 'npz_path'):
            clip.get('source_provenance', {}).pop(key, None)
    return {
        'contract': CONTRACT, 'schema_version': 1,
        'binding': {'clip_id': binding_id, 'source_sha256': source_hash,
                    'source_oriented': True, 'coordinate_convention': COORDINATES,
                    'frame_count': len(times), 'raw_digest': motion_digest(s0),
                    'display_digest': motion_digest(s2)},
        'processing': {'pipeline': ['decoded_PTS', 'frozen_raw_P2_masks',
                                   'S2_body_and_feet', 'O1_F1', 'H4'],
                       'smoothing_condition': 'S2', 'smoothing_passes': 1,
                       'original_masks_preserved': True,
                       'raw_missingness_preserved': True,
                       'interpolation': False, 'offline': True,
                       'camera_reference': 'fixed_default_only',
                       's2_config_sha256': file_sha(ROOT / 'vendor/config/smoothing.json'),
                       's2_core_sha256': file_sha(ROOT / 'vendor/tools/smoothing.py'),
                       'score_model_modified': False,
                       'actual_pose_accuracy': 'not_measured'},
        'raw_orientation': s0, 'display_orientation': s2,
        'reference_scale': reference_scale,
        'presentation_end_s': end,
    }


