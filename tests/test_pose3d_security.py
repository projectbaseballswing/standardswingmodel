"""Real bcrypt/login/bearer/owner checks with explicitly fake byte storage.

These are HTTP integration tests, not Supabase or real-video E2E claims.
"""
import gzip
import json
import uuid
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from api import database
from api.database import AuthSession,Pose3D,Swing
from api.auth import token_hash
from api.main import app
from api.jobs import Job
from api.pose3d import init_pose,persist_pose
from api.storage import LocalPrivateStorage,StorageError
from tests.video_fixture import VIDEO_BYTES

def login(client):
    user='auth-'+uuid.uuid4().hex
    assert client.post('/api/register',json={'id':user,'password':'test-safe-password','email':user+'@example.com','nickname':user}).status_code==200
    r=client.post('/api/login',json={'id':user,'password':'test-safe-password'})
    assert r.status_code==200
    data=r.json();assert data['user']==user and data['expires_in']==28800 and data['token_type']=='bearer'
    return user,data['access_token']
def bearer(token):return {'Authorization':'Bearer '+token}
def upload(client,token,**extra):
    return client.post('/api/analyses',headers=bearer(token),data={'handedness':'right',**extra},files={'video':('fixture.mp4',VIDEO_BYTES,'video/mp4')})
def seeded(user):
    job=Job(analysis_id=uuid.uuid4().hex,user_id=user,status='done',input={'handedness':'right','source_sha256':'f'*64},result={'overall':{'score':83.123},'model_version':'0.2'})
    app.state.jobs._add(job);init_pose(job);return job

def test_real_tokens_are_hashed_expire_revoke_and_guard_all_owner_paths(mock_settings,fake_storage):
    with TestClient(app) as c:
        a,ta=login(c);b,tb=login(c)
        with database.SessionLocal() as db:
            row=db.get(AuthSession,token_hash(ta));assert row.user_id==a and row.token_hash!=ta
        made=upload(c,ta);assert made.status_code==202
        aid=made.json()['analysis_id']
        for url in [f'/api/analyses/{aid}',f'/api/analyses/{aid}/pose-3d',f'/api/analyses/{aid}/video',f'/api/analyses/{aid}/overall',f'/api/users/{a}/swings']:
            assert c.get(url).status_code==401
            assert c.get(url,headers=bearer('invalid-token')).status_code==401
            assert c.get(url,headers=bearer(tb)).status_code==403
        assert c.get(f'/api/analyses/{aid}',headers=bearer(ta)).json()['user_id']==a
        assert c.get('/api/analyses/'+'0'*32+'/pose-3d',headers=bearer(ta)).status_code==404
        assert upload(c,ta,user_id=b).status_code==403
        assert c.post('/api/me',headers=bearer(ta),json={'user':b}).status_code==403
        assert c.get(f'/api/analyses/{aid}/pose-3d',headers=bearer(ta)).json()['error']['code']=='MOCK_HAS_NO_WORLD'
        assert c.post('/api/logout',headers=bearer(ta)).status_code==200
        assert c.get(f'/api/analyses/{aid}',headers=bearer(ta)).status_code==401
        with database.SessionLocal.begin() as db:
            db.get(AuthSession,token_hash(tb)).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
        assert c.get(f'/api/users/{b}/swings',headers=bearer(tb)).status_code==401

def test_pose_processing_ready_private_roundtrip_and_tamper_rejection(mock_settings,fake_storage,monkeypatch):
    with TestClient(app) as c:
        user,token=login(c);other,other_token=login(c);job=seeded(user)
        url=f'/api/analyses/{job.analysis_id}/pose-3d'
        pending=c.get(url,headers=bearer(token));assert pending.status_code==202 and pending.json()['status']=='pending' and 'clip' not in pending.json()
        with database.SessionLocal.begin() as db:db.get(Pose3D,job.analysis_id).status='processing'
        assert c.get(url,headers=bearer(token)).json()['status']=='processing'
        # Deliberately minimal payload: this test checks persistence, not geometry.
        clip={'id':job.analysis_id,'analysis_id':job.analysis_id,'data_kind':'analysis','frame_count':2,'timestamps_s':[0,.1],'coordinate_convention':'source_view_hip_centered_xright_yup_zcamera','warnings':['test fixture quality warning'],'frames':[{'positions':[None]*12}]*2}
        import feedback.pose3d
        monkeypatch.setattr(feedback.pose3d,'build_pose3d',lambda *args,**kwargs:clip)
        persist_pose(job,SimpleNamespace(pose3d_capture={}),lambda:fake_storage)
        reply=c.get(url,headers=bearer(token));assert reply.status_code==200
        assert reply.json()['clip']==clip and reply.json()['user_id']==user
        assert 'storage_path' not in reply.json() and 'storage_bucket' not in reply.json()
        assert 'url' not in reply.json() and reply.headers['cache-control']=='private, no-store'
        assert c.get(url,headers=bearer(other_token)).status_code==403
        with database.SessionLocal() as db:
            row=db.get(Pose3D,job.analysis_id);path=row.storage_path
            assert row.status=='ready' and row.compressed_size_bytes<len(json.dumps(clip).encode())
            assert db.get(Swing,job.analysis_id).result==job.result
        assert json.loads(gzip.decompress(fake_storage.objects[path]))==clip
        fake_storage.objects[path]=gzip.compress(b'{"data_kind":"sample"}')
        assert c.get(url,headers=bearer(token)).status_code==502
        del fake_storage.objects[path]
        assert c.get(url,headers=bearer(token)).status_code==404

@pytest.mark.parametrize('failure',['missing_capture','build_error','storage_error'])
def test_pose_failure_does_not_change_done_score(mock_settings,fake_storage,monkeypatch,failure):
    with TestClient(app) as c:
        user,token=login(c);job=seeded(user)
        import feedback.pose3d
        def build(*args,**kwargs):
            if failure=='build_error':raise ValueError('bad world observations')
            return {'id':job.analysis_id,'analysis_id':job.analysis_id,'data_kind':'analysis','frame_count':1,'timestamps_s':[0],'coordinate_convention':'source_view_hip_centered_xright_yup_zcamera'}
        monkeypatch.setattr(feedback.pose3d,'build_pose3d',build)
        if failure=='storage_error':
            def fail(*a,**k):raise StorageError('fixture failure')
            monkeypatch.setattr(fake_storage,'upload',fail)
        skeleton=None if failure=='missing_capture' else SimpleNamespace(pose3d_capture={})
        persist_pose(job,skeleton,lambda:fake_storage)
        with database.SessionLocal() as db:
            score=db.get(Swing,job.analysis_id);pose=db.get(Pose3D,job.analysis_id)
            assert score.status=='done' and score.result==job.result and pose.status=='failed'
        reply=c.get(f'/api/analyses/{job.analysis_id}/pose-3d',headers=bearer(token))
        assert reply.status_code==422 and 'clip' not in reply.json()

def test_local_storage_is_private_bounded_and_traversal_safe(tmp_path):
    s=LocalPrivateStorage(tmp_path/'private')
    f=tmp_path/'original.mp4';f.write_bytes(b'video')
    s.upload('swings/abc/original.mp4',str(f),'video/mp4')
    assert s.download(s.bucket,'swings/abc/original.mp4')==b'video'
    with pytest.raises(StorageError):s.download(s.bucket,'../original.mp4')
    with pytest.raises(StorageError):s.download(s.bucket,'swings/abc/original.mp4',max_bytes=1)
    with pytest.raises(StorageError):s.capability_path('pose3d/a/data.gz',9999999999,'forged')
    with pytest.raises(StorageError):LocalPrivateStorage('C:/Windows')


@pytest.mark.parametrize('code,expected', [
    ('INVALID_VIDEO_PTS', 'INVALID_VIDEO_PTS'),
    ('WORLD_FRAME_ALIGNMENT', 'WORLD_FRAME_ALIGNMENT'),
    ('PRIVATE_LIBRARY_DIAGNOSTIC', 'POSE3D_FAILED'),
])
def test_capture_error_without_capture_keeps_safe_cause_and_score(mock_settings, fake_storage, code, expected):
    with TestClient(app) as client:
        user, token = login(client)
        job = seeded(user)
        # No capture was produced, but the pipeline knows why. This must reach
        # build_pose3d rather than being replaced with generic missing World.
        skeleton = SimpleNamespace(pose3d_capture=None, pose3d_error={
            'code': code, 'message': 'private-library-message-and-credential',
        })
        persist_pose(job, skeleton, lambda: fake_storage)
        reply = client.get(f'/api/analyses/{job.analysis_id}/pose-3d', headers=bearer(token))
        assert reply.status_code == 422
        assert reply.json()['error']['code'] == expected
        assert 'private-library-message-and-credential' not in reply.text
        assert 'PRIVATE_LIBRARY_DIAGNOSTIC' not in reply.text
        with database.SessionLocal() as db:
            saved = db.get(Swing, job.analysis_id)
            assert saved.status == 'done' and saved.result == job.result
        assert not fake_storage.objects


@pytest.mark.parametrize('part', ['clip', 'envelope'])
def test_unusable_response_size_fails_before_storage_and_preserves_score(mock_settings, fake_storage, monkeypatch, part):
    import api.pose3d as api_pose
    import feedback.pose3d as build_pose

    # Small test bounds exercise the same byte-count guards without allocating
    # a 32 MiB fixture. The envelope duplicates warnings from the clip.
    monkeypatch.setattr(api_pose, 'MAX_RAW_BYTES', 4096)
    monkeypatch.setattr(api_pose, 'MAX_RESPONSE_BYTES', 6144)
    with TestClient(app) as client:
        user, token = login(client)
        job = seeded(user)
        clip = {'id': job.analysis_id, 'analysis_id': job.analysis_id, 'data_kind': 'analysis',
                'frame_count': 1, 'timestamps_s': [0], 'coordinate_convention': 'test',
                'warnings': ['x' * 1800] if part == 'envelope' else [],
                'frames': [{'padding': 'x' * 5000}] if part == 'clip' else []}
        monkeypatch.setattr(build_pose, 'build_pose3d', lambda *args, **kwargs: clip)
        persist_pose(job, SimpleNamespace(pose3d_capture={}), lambda: fake_storage)
        response = client.get(f'/api/analyses/{job.analysis_id}/pose-3d', headers=bearer(token))
        assert response.status_code == 422
        assert response.json()['error']['code'] == 'POSE3D_TOO_LARGE'
        assert not fake_storage.objects
        with database.SessionLocal() as db:
            saved = db.get(Swing, job.analysis_id)
            assert saved.status == 'done' and saved.result == job.result
            assert db.get(Pose3D, job.analysis_id).storage_path is None
