"""No remote resources: real HTTP auth + temporary SQLite/local Storage files."""
import copy
import gzip
import hashlib
import json
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.database import SessionLocal, Swing, Pose3D
from api.storage import LocalPrivateStorage, StorageError, StorageObjectNotFound
from tests.auth_helpers import authenticate
from tests.test_storage import storage_with_transport


@pytest.fixture
def original(mock_client, tmp_path):
    client = mock_client
    storage = LocalPrivateStorage(tmp_path / 'private')
    client.app.state.storage = storage
    identifier = uuid.uuid4().hex
    path = f'swings/{identifier}/original.mp4'
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'isolated-original-video')
    storage.upload(path, str(source), 'video/mp4')
    storage.upload('unrelated/keep.mp4', str(source), 'video/mp4')
    from api.analyses import _mock_report
    result = _mock_report()
    result['coaching'] = {'overall_summary': 'kept summary', 'overall_coach': 'kept coaching', 'parts': []}
    clip = {'id': identifier, 'analysis_id': identifier, 'data_kind': 'analysis', 'frames': []}
    raw = json.dumps(clip).encode()
    compressed = gzip.compress(raw)
    pose_path = f'pose3d/test-owner/{identifier}/display-v1.json.gz'
    pose_source = tmp_path / 'pose.gz'; pose_source.write_bytes(compressed)
    storage.upload(pose_path, str(pose_source), 'application/gzip')
    with SessionLocal.begin() as db:
        db.add(Swing(analysis_id=identifier, user_id=client.test_user_id, status='done',
                     worker_id='delete-tests', recorded_at=datetime.now(timezone.utc),
                     video_storage_path=path, storage_bucket=storage.bucket, video_size_bytes=source.stat().st_size,
                     content_type='video/mp4', input={'type': 'video', 'handedness': 'right'}, result=result))
        db.flush()
        db.add(Pose3D(analysis_id=identifier, user_id=client.test_user_id, status='ready',
                      storage_path=pose_path, storage_bucket=storage.bucket, warnings=[],
                      raw_size_bytes=len(raw), compressed_size_bytes=len(compressed), payload_sha256=hashlib.sha256(raw).hexdigest()))
    return client, storage, identifier, path


def url(identifier):
    return f'/api/analyses/{identifier}/video'


def snapshot(identifier):
    with SessionLocal() as db:
        swing = db.get(Swing, identifier); pose = db.get(Pose3D, identifier)
        return (copy.deepcopy({c.name: getattr(swing, c.name) for c in Swing.__table__.columns
                               if c.name not in {'video_storage_path', 'storage_bucket', 'video_size_bytes', 'content_type',
                                                 'video_delete_requested_at', 'video_deleted_at'}}),
                copy.deepcopy({c.name: getattr(pose, c.name) for c in Pose3D.__table__.columns}))


def test_owner_deletes_only_original_and_keeps_all_analysis_and_pose(original):
    client, storage, identifier, path = original
    before = snapshot(identifier)
    signed = client.get(url(identifier)).json()['url']
    assert client.get(signed).status_code == 200
    pose_before = client.get(f'/api/analyses/{identifier}/pose-3d')
    assert pose_before.status_code == 200
    feedback = {part: client.get(f'/api/analyses/{identifier}/{part}').json()
                for part in ['overall', 'joints', 'phases', 'coaching']}
    deleted = client.delete(url(identifier))
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {'analysis_id': identifier, 'video_status': 'deleted', 'already_deleted': False}
    assert not storage._path(path).exists()
    assert storage._path('unrelated/keep.mp4').read_bytes() == b'isolated-original-video'
    assert snapshot(identifier) == before
    assert client.get(url(identifier)).status_code == 410
    assert client.get(signed).status_code in (404, 410)
    assert client.get(f'/api/analyses/{identifier}').json()['video_status'] == 'deleted'
    assert client.get(f'/api/analyses/{identifier}/pose-3d').json() == pose_before.json()
    for part, value in feedback.items():
        assert client.get(f'/api/analyses/{identifier}/{part}').json() == value
    # Both calendar and all-history (trend) retain the date, score, ID and status.
    for query in ['', f'?year={datetime.now(timezone.utc).year}&month={datetime.now(timezone.utc).month}&tz_offset_minutes=0']:
        items = client.get(f'/api/users/{client.test_user_id}/swings{query}').json()['items']
        row = next(r for r in items if r['analysis_id'] == identifier)
        assert row['video_status'] == 'deleted' and row['status'] == 'done'
        assert row['score'] == before[0]['result']['overall']['score']
    with SessionLocal() as db:
        row = db.get(Swing, identifier)
        assert row.video_deleted_at and row.video_delete_requested_at
        assert (row.video_storage_path, row.storage_bucket, row.video_size_bytes, row.content_type) == (None, None, None, None)


def test_repeat_delete_is_success_without_storage_access(original, monkeypatch):
    client, storage, identifier, _ = original
    assert client.delete(url(identifier)).status_code == 200
    monkeypatch.setattr(storage, 'delete', lambda *args: pytest.fail('repeat must not touch Storage'))
    assert client.delete(url(identifier)).json()['already_deleted'] is True


@pytest.mark.parametrize('case,expected', [('anonymous', 401), ('other-user', 403), ('unknown-id', 404)])
def test_access_checks_never_touch_files(original, case, expected):
    client, storage, identifier, path = original
    if case == 'anonymous': client.headers.pop('Authorization')
    if case == 'other-user': authenticate(client)
    assert client.delete(url(uuid.uuid4().hex if case == 'unknown-id' else identifier)).status_code == expected
    assert storage._path(path).exists()
    with SessionLocal() as db: assert db.get(Swing, identifier).video_delete_requested_at is None


@pytest.mark.parametrize('status,pose_status', [('queued', 'pending'), ('processing', 'processing'), ('done', 'pending'), ('done', 'processing')])
def test_analysis_and_pose_processing_are_blocked(original, status, pose_status):
    client, storage, identifier, path = original
    with SessionLocal.begin() as db:
        db.get(Swing, identifier).status = status
        db.get(Pose3D, identifier).status = pose_status
    assert client.delete(url(identifier)).status_code == 409
    assert storage._path(path).exists()


def test_storage_failure_blocks_signing_and_old_local_capability_until_retry(original, monkeypatch):
    client, storage, identifier, path = original
    signed = client.get(url(identifier)).json()['url']
    before = snapshot(identifier)
    def broken(*args): raise StorageError('private upstream data must not escape')
    with monkeypatch.context() as m:
        m.setattr(storage, 'delete', broken)
        response = client.delete(url(identifier))
        assert response.status_code == 502 and 'private upstream' not in response.text
    assert storage._path(path).exists() and snapshot(identifier) == before
    assert client.get(url(identifier)).status_code == 409
    assert client.get(signed).status_code == 410
    # A fresh storage object, using the durable DB intent, finishes the retry.
    client.app.state.storage = LocalPrivateStorage(storage.root)
    assert client.delete(url(identifier)).status_code == 200
    assert not storage._path(path).exists()


@pytest.mark.parametrize('failed_commit', [1, 2])
def test_db_failures_leave_recoverable_state(original, monkeypatch, failed_commit):
    client, storage, identifier, path = original
    before = snapshot(identifier); commit = Session.commit; count = 0
    def failing_commit(db):
        nonlocal count
        count += 1
        if count == failed_commit: raise SQLAlchemyError('synthetic private DB detail')
        return commit(db)
    with monkeypatch.context() as m:
        m.setattr(Session, 'commit', failing_commit)
        response = client.delete(url(identifier))
    assert response.status_code == 503 and 'private DB' not in response.text
    assert storage._path(path).exists() == (failed_commit == 1)
    assert snapshot(identifier) == before
    assert client.delete(url(identifier)).status_code == 200
    assert snapshot(identifier) == before


def test_missing_storage_object_is_reconciled(original):
    client, storage, identifier, path = original
    storage.delete(storage.bucket, path)
    assert client.delete(url(identifier)).status_code == 200
    assert client.get(url(identifier)).status_code == 410


@pytest.mark.parametrize('path', ['pose3d/other/display.json.gz', 'swings/other/original.mp4', '../outside.mp4', 'swings'])
def test_malformed_db_target_cannot_delete_other_data(original, path):
    client, storage, identifier, original_path = original
    with SessionLocal.begin() as db: db.get(Swing, identifier).video_storage_path = path
    assert client.delete(url(identifier)).status_code == 409
    assert storage._path(original_path).exists()


def test_request_body_cannot_choose_storage_target(original):
    client, storage, identifier, path = original
    response = client.request('DELETE', url(identifier), json={'path': 'unrelated/keep.mp4', 'bucket': 'other'})
    assert response.status_code == 200
    assert not storage._path(path).exists() and storage._path('unrelated/keep.mp4').exists()


def test_failed_analysis_can_delete_its_original(original):
    client, _, identifier, _ = original
    with SessionLocal.begin() as db:
        db.get(Swing, identifier).status = 'failed'
        db.get(Pose3D, identifier).status = 'failed'
    assert client.delete(url(identifier)).status_code == 200


def test_supabase_single_object_delete_contract():
    seen = []
    def handler(request):
        seen.append(request)
        assert request.method == 'DELETE'
        assert request.url.path == '/storage/v1/object/test-videos/swings/abc/original.mp4'
        assert not request.content
        return httpx.Response(200, json={'message': 'Successfully deleted'})
    storage = storage_with_transport(handler)
    try:
        storage.delete('test-videos', 'swings/abc/original.mp4')
        with pytest.raises(StorageError): storage.delete('other', 'swings/abc/original.mp4')
        with pytest.raises(StorageError): storage.delete('test-videos', '../original.mp4')
        assert len(seen) == 1
    finally: storage.close()


@pytest.mark.parametrize('status,body,kind', [
    (404, {'code': 'NoSuchKey'}, StorageObjectNotFound),
    (400, {'message': 'Object not found'}, StorageObjectNotFound),
    (404, {'code': 'NoSuchBucket'}, StorageError), (404, {}, StorageError),
    (401, {}, StorageError), (403, {}, StorageError), (500, {}, StorageError),
])
def test_supabase_delete_errors_are_not_false_success(status, body, kind):
    storage = storage_with_transport(lambda request: httpx.Response(status, json=body))
    try:
        with pytest.raises(kind) as error: storage.delete('test-videos', 'swings/abc/original.mp4')
        if kind is StorageError: assert not isinstance(error.value, StorageObjectNotFound)
    finally: storage.close()


def test_local_delete_rejects_wrong_bucket_directory_escape_and_links(tmp_path):
    storage = LocalPrivateStorage(tmp_path/'private'); src = tmp_path/'source'; src.write_bytes(b'keep')
    storage.upload('safe/file.mp4', str(src), 'video/mp4')
    for bucket, path in [('other', 'safe/file.mp4'), (storage.bucket, '../source'), (storage.bucket, 'safe')]:
        with pytest.raises(StorageError): storage.delete(bucket, path)
    assert src.read_bytes() == storage._path('safe/file.mp4').read_bytes() == b'keep'
    link = storage.root/'linked.mp4'
    try: link.symlink_to(storage.root/'safe/file.mp4')
    except OSError: pytest.skip('OS does not permit creating symlinks')
    with pytest.raises(StorageError): storage.delete(storage.bucket, 'linked.mp4')
    assert storage._path('safe/file.mp4').read_bytes() == b'keep'
