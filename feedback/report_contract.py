"""Report interpretation and comparison guards; no scoring or event changes."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re

LEGACY_VERSIONS = {'0.2', '0.2-draft', '0.2.1', '0.2.1-draft', '0.2.2', '0.2.2-draft'}
CURRENT_VERSIONS = {'0.2.3', '0.2.3-draft'}


def report_version(report):
    if not isinstance(report, dict):
        return None
    overall = report.get('overall')
    values = [report.get('model_version'), overall.get('model_version') if isinstance(overall, dict) else None]
    supplied = [x for x in values if x is not None]
    if not supplied or any(not isinstance(x, str) or not x for x in supplied) or len(set(supplied)) != 1:
        return None
    return supplied[0]


def measurement_family(version):
    if version in LEGACY_VERSIONS:
        return 'shoulder-width-v1'
    if version in CURRENT_VERSIONS:
        return 'torso-leg-v2'
    return None


def measurement_semantics(key, version, fallback):
    family = measurement_family(version)
    relative = {
        'hand_x_from_shoulder': '양손목 중심과 양어깨 중심의 화면상 앞뒤 상대 위치',
        'hand_y_from_shoulder': '양손목 중심과 양어깨 중심의 화면상 상대 높이',
        'shoulder_x_from_hip': '양어깨 중심과 골반 중심의 화면상 앞뒤 상대 위치',
        'shoulder_y_from_hip': '양어깨 중심과 골반 중심의 화면상 상대 높이',
        'lead_ankle_x_from_hip': '앞발목과 골반 중심의 화면상 앞뒤 상대 위치',
    }
    if key in relative:
        if family is None:
            return relative[key] + '. 저장 모델의 정규화 정의가 미확인이라 단위를 단정하지 않음.' + (' 실제 보폭·스탠스 폭·이동 거리가 아님.' if key=='lead_ankle_x_from_hip' else '')
        scale = '몸통 길이' if family == 'torso-leg-v2' and key != 'lead_ankle_x_from_hip' else '어깨너비'
        suffix = ' 실제 보폭·스탠스 폭·발 이동 거리가 아님.' if key == 'lead_ankle_x_from_hip' else ' 실제 거리(cm)가 아님.'
        return relative[key] + f'를 {scale} 기준으로 정규화.' + suffix
    if key == 'lead_ankle_y_from_hip':
        if family == 'torso-leg-v2':
            return '뒷발목을 바닥 기준으로 삼은 앞발목의 화면상 상대 높이 / 양쪽 다리 길이 평균의 중앙값. 실제 바닥 높이·체형 독립성을 보장하지 않음.'
        if family == 'shoulder-width-v1':
            return '골반 중심 기준 앞발목의 화면상 상대 높이 / 어깨너비. 실제 지면에서 들어 올린 높이가 아님.'
        return '앞발 높이의 저장 모델별 기준점·정규화 정의가 미확인. 최신 뒷발목/다리 길이 정의를 적용하지 않음.'
    return fallback


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def phase_support_reason(phase, fps=None):
    """Duration uses end-start intervals; resampling includes BOTH endpoints.

    Withhold coaching at <=2 intervals (2-3 observed samples), independently of
    the 20-point display curve. This is a conservative display policy, not a
    newly measured reliability score or a statement about event accuracy.
    """
    frames = phase.get('user_frames') if isinstance(phase, dict) else None
    if not isinstance(frames, list) or len(frames) != 2:
        return 'phase_frames_missing'
    if any(not isinstance(x, int) or isinstance(x, bool) or x < 0 for x in frames) or frames[1] <= frames[0]:
        return 'phase_frames_invalid'
    count = frames[1] - frames[0]
    if count <= 2:
        return 'phase_too_short'
    if fps is not None:
        if not _number(fps) or fps <= 0:
            return 'phase_timing_invalid'
        duration = phase.get('user_duration_ms')
        if duration is not None:
            expected = count / fps * 1000
            if not _number(duration) or abs(duration - expected) > max(1.1, expected * .001):
                return 'phase_timing_inconsistent'
    return None


def build_analysis_contract(model, *, handedness):
    """Stamp new jobs only, using the exact reference loaded by that worker."""
    if model is None or not measurement_family(model.model_version):
        return None
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in ('compare_v2.py', 'swing_features.py', 'events.py', 'event_lstm.py', 'reference_model.py', 'features.py'):
        source = root / name
        if not source.is_file():
            return None
        digest.update(name.encode() + b'\0' + source.read_bytes().replace(b'\r\n', b'\n'))
    weights = root / 'event_lstm.npz'
    digest.update(b'event_lstm.npz\0' + (weights.read_bytes() if weights.is_file() else b'absent'))
    reference = Path(model.path)
    if not reference.is_file():
        return None
    return {'schema': 'swing-comparison-v1', 'model_version': model.model_version,
            'reference_sha256': hashlib.sha256(reference.read_bytes()).hexdigest(),
            'scoring_sha256': digest.hexdigest(), 'measurement_definition': measurement_family(model.model_version),
            'handedness': handedness}


def comparison_compatibility(current, previous):
    """Fail closed for historical records without proven scoring provenance."""
    a, b = report_version(current), report_version(previous)
    if a is None or b is None:
        return False, 'model_version_missing'
    if a != b:
        return False, 'model_version_mismatch'
    contracts = [r.get('analysis_contract') for r in (current, previous)]
    for c in contracts:
        if not isinstance(c, dict) or c.get('schema') != 'swing-comparison-v1':
            return False, 'comparison_metadata_missing'
        if c.get('model_version') != a or c.get('measurement_definition') != measurement_family(a) or measurement_family(a) is None:
            return False, 'comparison_metadata_invalid'
        if any(not isinstance(c.get(k), str) or not re.fullmatch(r'[a-f0-9]{64}', c[k]) for k in ('reference_sha256', 'scoring_sha256')):
            return False, 'comparison_metadata_invalid'
        if c.get('handedness') not in ('left', 'right'):
            return False, 'comparison_metadata_invalid'
    c, p = contracts
    for key, reason in [('reference_sha256', 'reference_model_mismatch'), ('scoring_sha256', 'scoring_definition_mismatch'),
                        ('handedness', 'handedness_mismatch')]:
        if c[key] != p[key]:
            return False, reason
    return True, 'compatible'
