"""Display-only World capture and EXP-007 packet builder.

Observes the existing MediaPipe call; IMAGE scoring outputs are never replaced.
Raw World, raw IMAGE quality and S2 display coordinates remain separate channels.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from feedback import pose3d_policy as policy
from feedback.pose3d_display.preprocess import package

BODY = policy.JOINTS
BODY_INDICES = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]
FEET = ['left_heel', 'right_heel', 'left_foot_index', 'right_foot_index']
FOOT_INDICES = [29, 30, 31, 32]
SWAP = [1, 0, 3, 2, 5, 4, 7, 6, 9, 8, 11, 10]
FOOT_SWAP = [1, 0, 3, 2]
CONVENTION = 'source_view_hip_centered_xright_yup_zcamera'
P2_SHA = hashlib.sha256(Path(policy.__file__).read_bytes()).hexdigest()


class Pose3DError(ValueError):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def _xyz(landmarks, indices):
    points = np.full((len(indices), 3), np.nan)
    for j, index in enumerate(indices):
        if index < len(landmarks):
            point = landmarks[index]
            xyz = np.asarray([point.x, point.y, point.z], dtype=float)
            if np.isfinite(xyz).all():
                points[j] = xyz
    return points


def _visibility(landmarks, indices):
    return np.asarray([getattr(landmarks[i], 'visibility', np.nan)
                       if i < len(landmarks) else np.nan for i in indices], float)


class Pose3DCapture:
    """Optional observer, with all failures isolated from IMAGE inference."""
    def __init__(self, pts, is_left, width, height, fps):
        self.pts = list(pts)
        self.is_left = bool(is_left)
        self.width, self.height, self.fps = int(width), int(height), float(fps)
        self.world, self.feet = [], []
        self.visibility, self.foot_visibility, self.image = [], [], []
        self.rois, self.masks = [], None
        self.error = None

    def fail(self):
        self.error = {'code': 'WORLD_CAPTURE_FAILED',
                      'message': '3D 좌표 보존에 실패했습니다. 기존 점수 결과는 별도로 제공됩니다.'}

    def record(self, index, result, roi_info, roi_size):
        if index != len(self.world):
            raise ValueError('Observer frame alignment mismatch')
        worlds = getattr(result, 'pose_world_landmarks', None) if result else None
        images = getattr(result, 'pose_landmarks', None) if result else None
        world = worlds[0] if worlds else []
        image = images[0] if images else []
        self.world.append(_xyz(world, BODY_INDICES))
        self.feet.append(_xyz(world, FOOT_INDICES))
        self.visibility.append(_visibility(image, BODY_INDICES))
        self.foot_visibility.append(_visibility(image, FOOT_INDICES))
        raw_image = _xyz(image, BODY_INDICES)
        if roi_size and roi_info:
            from modules.utils.pose_preprocessing import restore_landmarks_to_original_frame
            rw, rh = roi_size
            raw_image *= np.asarray([rw, rh, rw])
            raw_image = restore_landmarks_to_original_frame(raw_image, roi_info)
        else:
            raw_image[:] = np.nan
        self.image.append(raw_image)
        self.rois.append(copy.deepcopy(roi_info))

    def quality(self, raw_df, filtered_df):
        """Reproduce existing IMAGE masks read-only; never feed them to scoring."""
        from modules.utils.pose_preprocessing import (
            apply_edge_fill, collapse_bad_frames, compute_motion_missing,
            compute_shoulder_width_median, compute_visibility_missing,
            interpolate_short_gaps,
        )
        from modules.utils.pose_utils import MAX_INTERP_GAP_FRAMES, MAX_INTERP_GAP_FRAMES_BY_JOINT
        vis = compute_visibility_missing(raw_df)
        width = compute_shoulder_width_median(raw_df, vis)
        combined = collapse_bad_frames(vis | compute_motion_missing(raw_df, vis, width))
        filled, after = apply_edge_fill(raw_df, combined)
        interpolated = np.zeros((len(raw_df), 12), dtype=bool)
        for j, name in enumerate(BODY):
            missing = after[name].to_numpy(dtype=bool)
            raw = filled[f'{name}_x'].to_numpy(dtype=float).copy()
            raw[missing] = np.nan
            values = interpolate_short_gaps(raw, missing,
                MAX_INTERP_GAP_FRAMES_BY_JOINT.get(name, MAX_INTERP_GAP_FRAMES))
            interpolated[:, j] = missing & np.isfinite(values)
        self.masks = {
            'combined_missing': combined[BODY].to_numpy(dtype=bool),
            'edge_filled': (combined[BODY] & ~after[BODY]).to_numpy(dtype=bool),
            'interpolated': interpolated,
        }

    def finish(self):
        if self.error:
            raise Pose3DError(self.error['code'], self.error['message'])
        times = np.asarray(self.pts, float)
        count = len(self.world)
        if count == 0 or count != len(times) or self.masks is None:
            raise Pose3DError('WORLD_FRAME_ALIGNMENT', '영상 시간과 3D 관절 프레임 수가 일치하지 않습니다.')
        if not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
            raise Pose3DError('INVALID_VIDEO_PTS', '영상의 실제 timestamp를 검증할 수 없어 3D를 생성하지 않았습니다.')
        world = np.asarray(self.world, float)
        if not np.isfinite(world).all(axis=-1).any():
            raise Pose3DError('WORLD_NOT_AVAILABLE', 'MediaPipe World 관절을 확보하지 못했습니다.')
        return {'world_raw': world, 'foot_world_raw': np.asarray(self.feet, float),
                'visibility_raw': np.asarray(self.visibility, float),
                'foot_visibility_raw': np.asarray(self.foot_visibility, float),
                'image_pixel_raw': np.asarray(self.image, float),
                'image_quality': self.masks, 'decoded_pts_s': times,
                'fps': self.fps, 'width': self.width, 'height': self.height,
                'mirrored_input': self.is_left, 'handedness': 'left' if self.is_left else 'right',
                'roi_infos': self.rois,
                'inference_reused': True, 'additional_pose_inference_calls': 0,
                'mediapipe_time_source': 'existing nominal frame_index/fps; unchanged for score parity',
                'display_time_source': 'decoded video PTS'}


def observe(capture, method, *args):
    """An optional display observer must never break the established scorer."""
    if capture is None or capture.error:
        return
    try:
        getattr(capture, method)(*args)
    except Exception:
        capture.fail()


def _values(array):
    return [float(v) if np.isfinite(v) and 0 <= v <= 1 else None for v in array]


def restore_world(capture):
    """The one source-view restoration shared by all new uploads."""
    mirrored = capture['mirrored_input']
    if type(mirrored) is not bool:
        raise Pose3DError('AMBIGUOUS_COORDINATES', '좌우 반전 메타데이터가 올바르지 않습니다.')
    mapping = SWAP if mirrored else list(range(12))
    foot_mapping = FOOT_SWAP if mirrored else list(range(4))
    world = np.asarray(capture['world_raw'], float)[:, mapping].copy()
    feet = np.asarray(capture['foot_world_raw'], float)[:, foot_mapping].copy()
    visibility = np.asarray(capture['visibility_raw'], float)[:, mapping].copy()
    foot_visibility = np.asarray(capture['foot_visibility_raw'], float)[:, foot_mapping].copy()
    if mirrored:
        world[..., 0] *= -1
        feet[..., 0] *= -1
    roots = (world[:, 6] + world[:, 7]) * .5
    world -= roots[:, None]
    feet -= roots[:, None]
    world[..., 1:] *= -1
    feet[..., 1:] *= -1
    masks = {name: np.asarray(values, bool)[:, mapping].copy()
             for name, values in capture['image_quality'].items()}
    return world, feet, visibility, foot_visibility, masks, mapping, foot_mapping


def build_pose3d(skeleton, *, analysis_id, user_id, source_sha256):
    """Return strict JSON for this analysis; never select a player sample."""
    error = getattr(skeleton, 'pose3d_error', None)
    if error:
        raise Pose3DError(error['code'], error['message'])
    capture = getattr(skeleton, 'pose3d_capture', None)
    if not capture:
        raise Pose3DError('WORLD_NOT_CAPTURED', '이 분석에는 3D World 관절이 저장되지 않았습니다.')
    if not isinstance(analysis_id, str) or not analysis_id or not isinstance(user_id, str) or not user_id:
        raise Pose3DError('INVALID_ANALYSIS_BINDING', '검증된 분석과 소유자가 필요합니다.')
    times = np.asarray(capture['decoded_pts_s'], float)
    world, feet, visibility, foot_visibility, masks, mapping, foot_mapping = restore_world(capture)
    if len(times) != len(world) or not len(times) or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise Pose3DError('INVALID_VIDEO_PTS', '3D 좌표의 실제 시간축이 올바르지 않습니다.')
    times = times - times[0]
    fps = float(capture['fps'])
    if not np.isfinite(fps) or fps <= 0:
        raise Pose3DError('INVALID_VIDEO_FPS', '유효한 영상 FPS가 필요합니다.')
    rows, _ = policy.candidates(world, times, fps, visibility, masks)
    orientation_frames, body_frames = [], []
    for i, row in enumerate(rows):
        p2 = row['P2']
        p2_mask = {'edge_visible': p2['edge_visible'], 'torso_visible': p2['torso_visible'],
                   'joint_warnings': [state != 'observed' for state in p2['joint_states']],
                   'warnings': p2['warnings']}
        positions = policy.points(world[i])
        orientation_frames.append({'index': i, 'timestamp_s': float(times[i]),
            'decoded_pts_s': float(capture['decoded_pts_s'][i]),
            'positions': positions, 'feet': policy.points(feet[i]),
            'foot_visibility': _values(foot_visibility[i]), 'p2': p2_mask})
        body_frames.append({'index': i, 'timestamp_s': float(times[i]),
            'decoded_pts_s': float(capture['decoded_pts_s'][i]), 'positions': positions,
            'visibility': _values(visibility[i]),
            'observed_valid': np.isfinite(world[i]).all(axis=-1).tolist(),
            'image_quality_render': {**{k: v[i].tolist() for k, v in masks.items()},
                'provenance': 'Existing IMAGE filter masks, not World accuracy'},
            'warnings': p2['warnings'], 'manual_review_annotations': []})
    source = {'source_sha256': source_sha256, 'frame_width': capture['width'],
        'frame_height': capture['height'], 'body_render_to_npz': mapping,
        'foot_render_to_npz': foot_mapping, 'head_landmarks_present': False,
        'extraction': 'same MediaPipe invocation as model 0.2 IMAGE scoring',
        'p2_core_sha256': P2_SHA, 'world_units': 'MediaPipe model metres estimate, not calibrated motion capture',
        'image_z_is_not_world': True, 'additional_pose_inference_calls': 0}
    raw = {'schema_version': 1, 'id': analysis_id, 'title': '내 스윙',
        'handedness': capture['handedness'], 'coordinate_convention': CONVENTION,
        'source_oriented': True, 'mirrored_input': capture['mirrored_input'],
        'joint_names': BODY, 'foot_joint_names': FEET, 'frame_count': len(times), 'fps': fps,
        'source_provenance': source, 'frames': orientation_frames,
        'display_policy': {'id': 'P2', 'provenance': 'Frozen EXP-006 policy on original World observations'},
        'human_review': 'unreviewed'}
    final = package(raw, analysis_id)
    raw_orientation = copy.deepcopy(final['raw_orientation'])
    raw_orientation['binding'] = {'clip_id': analysis_id, 'source_sha256': source_sha256,
                                 'contract': 'EXP007-O1-binding-v1'}
    warnings = ['단안 World 추정 자세입니다. 실제 3D 정답이나 얼굴 추적 결과가 아닙니다.']
    if fps < 59:
        warnings.append('60FPS 이상 촬영을 권장합니다. 현재 영상은 실제 timestamp로 재생하며 프레임을 추가하지 않습니다.')
    if min(capture['width'], capture['height']) < 720:
        warnings.append('영상 해상도가 낮아 작은 관절의 위치가 불확실할 수 있습니다.')
    if any(any(r['P2']['joint_states'][j] != 'observed' for j in [2,3,4,5]) for r in rows):
        warnings.append('팔·손목 품질 경고가 있습니다. 원본 영상과 함께 확인하세요.')
    result = {'schema_version': 1, 'id': analysis_id, 'analysis_id': analysis_id,
        'data_kind': 'analysis', 'title': '내 스윙', 'coordinate_space': 'world',
        'coordinate_convention': CONVENTION, 'source_oriented': True,
        'mirrored_input': capture['mirrored_input'], 'handedness': capture['handedness'],
        'joint_names': BODY, 'frame_count': len(times), 'fps': fps,
        'timestamps_s': times.tolist(), 'render_to_npz_joint_indices': mapping,
        'frames': body_frames, 'orientation_data': raw_orientation,
        'final_display_data': final, 'presentation_end_s': final['presentation_end_s'],
        'source_provenance': {'source_video_sha256': source_sha256,
            'extraction': source['extraction'], 'p2_core_sha256': P2_SHA},
        'image_quality_note': 'IMAGE visibility/filter masks are quality hints, not World confidence.',
        'quality': {'measured_accuracy': False, 'human_review': 'unreviewed',
            'observed_world_joint_ratio': float(np.isfinite(world).all(axis=-1).mean()),
            'source_fps': fps, 'effective_pts_fps': float(1 / np.median(np.diff(times))) if len(times)>1 else None,
            'frame_width': capture['width'], 'frame_height': capture['height'],
            'warning_frames': sum(any(r['P2']['joint_states'][j] != 'observed' for j in range(12)) for r in rows)},
        'warnings': warnings,
        'raw_estimation': {
            'coordinate_convention': 'mediapipe_inference_world',
            'source_oriented': False, 'mirrored_input': capture['mirrored_input'],
            'joint_names': BODY, 'foot_joint_names': FEET,
            'world_raw': [policy.points(p) for p in capture['world_raw']],
            'foot_world_raw': [policy.points(p) for p in capture['foot_world_raw']],
            'visibility_raw': [_values(p) for p in capture['visibility_raw']],
            'foot_visibility_raw': [_values(p) for p in capture['foot_visibility_raw']],
            'decoded_pts_s': np.asarray(capture['decoded_pts_s'], float).tolist(),
            'note': 'Unmodified model World observations before source restoration, P2 or S2; IMAGE visibility is not world confidence.',
        },
        'inference_provenance': {'reused_existing_pose_call': True,
            'additional_pose_inference_calls': 0,
            'mediapipe_timestamp': capture.get('mediapipe_time_source'),
            'display_timestamp': 'decoded_pts_s; no interpolation'}}
    # Reject any accidental NaN before persistence; nulls are intentional.
    json.dumps(result, ensure_ascii=False, allow_nan=False)
    return result
