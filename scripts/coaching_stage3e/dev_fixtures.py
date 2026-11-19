"""Private local fixtures for the stage-3E app check; no remote resources."""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OWNER, OTHER = 'stage3e-review', 'stage3e-other'
IDS = {'approved': 'a' * 32, 'review_required': 'b' * 32,
       'blocked': 'c' * 32, 'generation_failed': 'd' * 32, 'other': 'e' * 32}
SYNTHETIC_TEXT = '격리 테스트: 승인 표시 흐름 확인용 예시'


def configure(folder: Path) -> None:
    os.environ.update(
        DATABASE_URL='sqlite:///' + str(folder / 'fixture.db'),
        SWING_DATABASE_SCHEMA='public', SWING_MOCK='1',
        SWING_WORKER_ID='stage3e-isolated-fixture', SWING_STORAGE_BACKEND='local',
        SWING_LOCAL_STORAGE_ROOT=str(folder / 'private'), SUPABASE_URL='',
        SUPABASE_SERVICE_ROLE_KEY='', SUPABASE_STORAGE_BUCKET='', OPENAI_API_KEY='',
        GEMINI_API_KEY='', GOOGLE_API_KEY='', OPENAI_COACHING_SCOPE='overall',
        RUN_SUPABASE_INTEGRATION_TESTS='0', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
    )


def prepare(folder: Path, password: str) -> Path:
    configure(folder)
    from api.database import engine, SessionLocal, User, Swing, Pose3D
    from api.security import hash_password
    from api.storage import LocalPrivateStorage
    from api.settings import settings
    from feedback.coaching_review import capture_review, approve_review, context_for
    from tests.video_fixture import VIDEO_BYTES
    from alembic import command
    from alembic.config import Config

    if (engine.url.get_backend_name() != 'sqlite'
            or not Path(engine.url.database).resolve().is_relative_to(folder.resolve())
            or settings.storage_backend != 'local' or settings.openai_api_key
            or settings.supabase_url or settings.supabase_service_role_key):
        raise RuntimeError('Only isolated SQLite/local storage with no API credentials is allowed')
    command.upgrade(Config(str(ROOT / 'alembic.ini')), 'head')
    storage = LocalPrivateStorage(folder / 'private')
    source = folder / 'synthetic-container.mp4'
    source.write_bytes(VIDEO_BYTES)  # Container fixture, not a playable or inferred swing.
    report = json.loads((ROOT / 'api/fixtures/analysis_sample.json').read_text(encoding='utf-8'))
    clip = json.loads((ROOT / 'frontend/test/fixtures/synthetic_left60.json').read_text(encoding='utf-8'))
    old_a = ROOT.parent / 'swing-feedback-stage3b/.local/feedback-stage3b/current-run/coaching.json'
    old_b = ROOT.parent / 'swing-feedback-stage3d/.local/feedback-stage3d/b-run/coaching.json'
    actual = {'blocked': json.loads(old_a.read_text(encoding='utf-8')),
              'review_required': json.loads(old_b.read_text(encoding='utf-8'))}
    candidate = {'overall_summary': SYNTHETIC_TEXT,
                 'overall_coach': '실제 GPT 품질 평가가 아닌 개발환경 승인 분기 테스트입니다.',
                 'coach_feedback': {'problem': '원본 영상에서 관찰 가능한 차이를 확인합니다.',
                                    'cause': '현재 분석만으로 원인을 확인하기 어렵습니다.',
                                    'fix': '원본 구간을 확인합니다.',
                                    'drill': '일반 연습 제안이며 교정 효과를 검증한 결과가 아닙니다.'},
                 'parts': []}
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    states = ['approved', 'review_required', 'blocked', 'generation_failed', 'other']
    with SessionLocal.begin() as db:
        for name in (OWNER, OTHER):
            db.add(User(user_id=name, email=name + '@example.invalid', nickname=name,
                        password_hash=hash_password(password)))
        db.flush()
        for index, state in enumerate(states):
            identifier, owner = IDS[state], OTHER if state == 'other' else OWNER
            result = copy.deepcopy(report)
            context = context_for(identifier, owner)
            generated = candidate if state == 'approved' else actual.get(state)
            envelope = capture_review(result, {'candidate': generated} if generated else {},
                                      context=context, scope='overall')
            if state == 'approved':
                envelope = approve_review(result, envelope, context=context,
                    reviewer_id='synthetic-test-reviewer',
                    note='Synthetic display fixture only. NOT human approval of actual GPT A/B.',
                    expected_candidate_sha256=envelope['candidate_sha256'])
            elif state != 'other' and envelope['status'] != state:
                raise AssertionError('Unexpected saved candidate policy status: ' + state)
            result['_coaching_review'] = envelope
            result['coaching'] = None
            date = now - timedelta(days=index * 2)
            video_path = f'swings/{identifier}/original.mp4'
            storage.upload(video_path, str(source), 'video/mp4')
            db.add(Swing(analysis_id=identifier, user_id=owner, status='done',
                         worker_id='synthetic-local-only', recorded_at=date, created_at=date,
                         video_storage_path=video_path, storage_bucket=storage.bucket,
                         video_size_bytes=source.stat().st_size, content_type='video/mp4',
                         input={'type': 'video', 'handedness': 'left'}, result=result))
            db.flush()
            data = copy.deepcopy(clip)
            data.update(id=identifier, analysis_id=identifier, title='격리 테스트용 합성 3D 좌표')
            data['orientation_data']['id'] = identifier
            data['orientation_data']['binding']['clip_id'] = identifier
            data['final_display_data']['binding']['clip_id'] = identifier
            raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            compressed = gzip.compress(raw, mtime=0)
            pose_source = folder / ('pose-' + identifier + '.gz')
            pose_source.write_bytes(compressed)
            pose_path = f'pose3d/fixture/{identifier}/display-v1.json.gz'
            storage.upload(pose_path, str(pose_source), 'application/gzip')
            db.add(Pose3D(analysis_id=identifier, user_id=owner, status='ready',
                         storage_path=pose_path, storage_bucket=storage.bucket,
                         raw_size_bytes=len(raw), compressed_size_bytes=len(compressed),
                         payload_sha256=hashlib.sha256(raw).hexdigest(), warnings=[],
                         frame_count=data['frame_count'], handedness='left',
                         timestamps_s=data['timestamps_s'], coordinate_convention=data['coordinate_convention']))
        # Flutter prefers the previous-swing envelope when history exists.
        # Exercise that gate too; actual A/B remain quarantined and unapproved.
        db.flush()
        for current_state, previous_state in zip(states[:3], states[1:4]):
            current = db.get(Swing, IDS[current_state])
            previous = db.get(Swing, IDS[previous_state])
            context = context_for(current.analysis_id, OWNER,
                previous_analysis_id=previous.analysis_id, previous=previous.result)
            generated = candidate if current_state == 'approved' else actual[current_state]
            envelope = capture_review(current.result, {'candidate': generated}, context=context,
                                      previous=previous.result, scope='overall')
            if current_state == 'approved':
                envelope = approve_review(current.result, envelope, context=context,
                    previous=previous.result, reviewer_id='synthetic-test-reviewer',
                    note='Synthetic comparison display fixture only; no actual A/B approval.',
                    expected_candidate_sha256=envelope['candidate_sha256'])
            elif envelope['status'] != current_state:
                raise AssertionError('Unexpected comparison policy state: ' + current_state)
            result = copy.deepcopy(current.result)
            result['comparison'] = {'previous_analysis_id': previous.analysis_id,
                                    '_coaching_review': envelope, 'coaching': None}
            current.result = result
    engine.dispose()
    (folder / 'fixture-description.json').write_text(json.dumps({
        'synthetic_only': True, 'actual_saved_A_B_approved': False,
        'records': IDS, 'source_A_sha256': hashlib.sha256(old_a.read_bytes()).hexdigest(),
        'source_B_sha256': hashlib.sha256(old_b.read_bytes()).hexdigest(),
        'video_limit': 'Storage container only; video decoding/inference not tested',
        'scores': 'Copied fixture scores, not actual user history',
    }, indent=2), encoding='utf-8')
    return storage.root / f'swings/{IDS["approved"]}/original.mp4'
