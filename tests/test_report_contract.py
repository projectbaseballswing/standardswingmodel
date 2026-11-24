"""Offline evidence/compatibility tests. Synthetic provenance is never migrated to real records."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from feedback.report_contract import (
    build_analysis_contract, comparison_compatibility, measurement_family,
    measurement_semantics, phase_support_reason, report_version,
)
from feedback.coaching_evidence import build_evidence_input


def contract(version='0.2.3-draft'):
    return {'schema': 'swing-comparison-v1', 'model_version': version,
            'reference_sha256': 'a'*64, 'scoring_sha256': 'b'*64,
            'measurement_definition': measurement_family(version),
            'handedness': 'right'}


def sample():
    return json.loads((Path(__file__).resolve().parents[1]/'api/fixtures/analysis_sample.json').read_text(encoding='utf-8'))


def proven():
    r=sample()
    r['analysis_contract']=contract(r['model_version'])
    return r


@pytest.mark.parametrize('key', ['hand_x_from_shoulder','hand_y_from_shoulder','shoulder_x_from_hip','shoulder_y_from_hip'])
def test_normalized_measurements_follow_stored_version(key):
    assert '몸통 길이' in measurement_semantics(key,'0.2.3-draft','')
    assert '어깨너비' in measurement_semantics(key,'0.2.2-draft','')
    assert '미확인' in measurement_semantics(key,None,'')


def test_front_foot_floor_reference_not_retroactive():
    assert '뒷발목' in measurement_semantics('lead_ankle_y_from_hip','0.2.3-draft','')
    assert '골반 중심' in measurement_semantics('lead_ankle_y_from_hip','0.2-draft','')
    assert '어깨너비' in measurement_semantics('lead_ankle_x_from_hip','0.2.3-draft','')
    assert '보폭' in measurement_semantics('lead_ankle_x_from_hip','0.2.3-draft','')
    assert report_version({'model_version':'0.2.3-draft','overall':{'model_version':'0.2.2-draft'}}) is None


@pytest.mark.parametrize(('change','reason'), [
    ({'reference_sha256':'c'*64},'reference_model_mismatch'),
    ({'scoring_sha256':'c'*64},'scoring_definition_mismatch'),
    ({'handedness':'left'},'handedness_mismatch'),
    ({'reference_sha256':'filename.npz'},'comparison_metadata_invalid'),
    ({'handedness':None},'comparison_metadata_invalid'),
])
def test_comparison_provenance_mismatch(change, reason):
    current,previous=proven(),proven()
    previous['analysis_contract'].update(change)
    before=copy.deepcopy((current,previous))
    assert comparison_compatibility(current,previous)==(False,reason)
    assert (current,previous)==before
    assert build_evidence_input(current,previous=previous)['comparison']['available'] is False


def test_no_legacy_provenance_is_not_assumed_compatible():
    a,b=sample(),sample()
    assert comparison_compatibility(a,b)==(False,'comparison_metadata_missing')
    a['model_version']='0.2.3-draft';a['overall']['model_version']='0.2.3-draft'
    assert comparison_compatibility(a,b)==(False,'model_version_mismatch')
    assert comparison_compatibility(a,None)==(False,'model_version_missing')
    assert comparison_compatibility(proven(),proven())==(True,'compatible')


def test_new_contract_stamps_actual_reference_without_touching_it(tmp_path):
    p=tmp_path/'reference.npz';p.write_bytes(b'fixture reference bytes')
    model=SimpleNamespace(path=p,model_version='0.2.3-draft')
    a=build_analysis_contract(model,handedness='left')
    assert a['handedness']=='left' and len(a['scoring_sha256'])==64
    assert p.read_bytes()==b'fixture reference bytes'
    p.write_bytes(b'different reference')
    b=build_analysis_contract(model,handedness='left')
    assert a['reference_sha256']!=b['reference_sha256']
    assert a['scoring_sha256']==b['scoring_sha256']


@pytest.mark.parametrize(('bounds','reason'), [
    ([25,26],'phase_too_short'),([25,27],'phase_too_short'),
    ([25,28],None),(None,'phase_frames_missing'),
    ([25,25],'phase_frames_invalid'),([True,6],'phase_frames_invalid'),
    ([25,24],'phase_frames_invalid'),([0.5,9],'phase_frames_invalid'),
])
def test_source_frames_not_resampled_length(bounds, reason):
    assert phase_support_reason({'user_frames':bounds,'series':[0]*20},30)==reason


def test_timing_mismatch_is_not_evidence_for_coaching():
    assert phase_support_reason({'user_frames':[0,3],'user_duration_ms':100},30) is None
    assert phase_support_reason({'user_frames':[0,3],'user_duration_ms':500},30)=='phase_timing_inconsistent'
    assert phase_support_reason({'user_frames':[0,3]},0)=='phase_timing_invalid'


def test_short_high_reliability_phase_withholds_both_strengths_and_corrections():
    r=sample()
    for phase in r['phases']['phases']:
        phase.update(user_frames=[0,2],user_duration_ms=2000/r['phases']['user_fps'],reliability='high')
    before=copy.deepcopy(r)
    evidence=build_evidence_input(r)
    assert not evidence['strengths'] and not evidence['priority_candidates']
    assert not evidence['allowed']['phases']
    assert any(x['reason']=='phase_too_short' for x in evidence['excluded'])
    assert r==before  # including stored scores, features and reliability


@pytest.mark.parametrize('condition', ['missing','model','reference','scoring','invalid_previous'])
def test_api_retains_previous_identity_but_no_incompatible_deltas(mock_client,condition):
    from datetime import datetime,timezone
    import uuid
    from tests.test_comparison import _swing,_seed,_result,_part
    from tests.auth_helpers import authenticate
    owner='contract-'+uuid.uuid4().hex
    current_result=_result(80,[_part('lead_arm','팔',80)])
    previous_result=_result(60,[_part('lead_arm','팔',60)])
    if condition=='missing':previous_result.pop('analysis_contract')
    elif condition=='model':previous_result['model_version']='0.2.2-draft'
    elif condition in ('reference','scoring'):previous_result['analysis_contract'][condition+'_sha256']='c'*64
    else:previous_result=None
    previous=_swing(owner,datetime(2026,1,1,tzinfo=timezone.utc),result=previous_result)
    current=_swing(owner,datetime(2026,1,2,tzinfo=timezone.utc),result=current_result)
    _seed([previous,current],user_ids=[owner]);authenticate(mock_client,owner)
    response=mock_client.get(f'/api/users/{owner}/analyses/{current.analysis_id}/comparison')
    assert response.status_code==200
    body=response.json()
    assert body['has_previous'] is True and body['previous_analysis_id']==previous.analysis_id
    assert body['comparable'] is False and body['overall_delta'] is None
    assert body['overall_previous_score'] is None and not body['parts'] and not body['phases'] and not body['joints']
    assert body['coaching'] is None and body['coaching_review']['display_allowed'] is False


def test_api_holds_low_quality_and_short_phase_deltas(mock_client):
    from datetime import datetime,timezone
    import uuid
    from tests.test_comparison import _swing,_seed,_rich_result,_part,_phase
    from tests.auth_helpers import authenticate
    owner='quality-'+uuid.uuid4().hex
    a=_rich_result(80,[_part('lead_arm','팔',80,reliability='low')],phases=[_phase('transition','준비',90)])
    b=_rich_result(60,[_part('lead_arm','팔',60)],phases=[_phase('transition','준비',60)])
    a['overall']['reliability']='low';a['phases']['phases'][0]['user_frames']=[3,5]
    prev=_swing(owner,datetime(2026,1,1,tzinfo=timezone.utc),result=b)
    curr=_swing(owner,datetime(2026,1,2,tzinfo=timezone.utc),result=a)
    _seed([prev,curr],user_ids=[owner]);authenticate(mock_client,owner)
    body=mock_client.get(f'/api/users/{owner}/analyses/{curr.analysis_id}/comparison').json()
    assert body['comparable'] is True and body['has_previous'] is True
    assert body['overall_delta'] is None and not body['parts'] and not body['phases']


def test_unknown_quality_does_not_become_valid_comparison():
    from api.swings import _joint_diffs, _phase_scores
    row=SimpleNamespace(status='done',result={
        'joints':[{'key':'lead_elbow_angle','available':True,'impact':{'diff':20}}],
        'phases':{'phases':[{'key':'swing','available':True,'user_frames':[0,10],'score':80}]}})
    assert _joint_diffs(row)=={} and _phase_scores(row)=={}


@pytest.mark.parametrize('left',[False,True])
def test_worker_stamps_contract_without_changing_computed_result(monkeypatch,tmp_path,left):
    import api.jobs as jobs
    import api.pose3d as pose3d
    r=sample();before=copy.deepcopy(r);snapshots=[]
    skeleton=SimpleNamespace(landmarks_pixel=[],fps=30)
    monkeypatch.setattr(jobs,'_skeleton_quality',lambda _: {})
    monkeypatch.setattr(jobs,'_world_landmarks',lambda _: None)
    monkeypatch.setattr(jobs,'_attach_motion',lambda *args: None)
    monkeypatch.setattr(jobs,'SwingComparisonV2',lambda *a,**k:SimpleNamespace(events={},report=lambda **k:copy.deepcopy(r)))
    monkeypatch.setattr(pose3d,'fail_pose',lambda *a:None)
    manager=jobs.JobManager.__new__(jobs.JobManager)
    manager.model_v2=object();manager.analysis_contract=contract(r['model_version'])
    manager._pipeline=SimpleNamespace(extract_skeleton=lambda *a,**k:skeleton)
    manager._supports_v2=lambda _:True
    manager._save=lambda job:snapshots.append(copy.deepcopy(job.result))
    manager._attach_overall_coaching=lambda job:None
    manager._make_thumbnail=lambda *a:None
    manager._pose_storage_factory=None;manager.coaching_scope='overall'
    video=tmp_path/'owned-test-input.mp4';video.write_bytes(b'synthetic-unused-input')
    job=jobs.Job('synthetic-job',{})
    manager._run_video(job,str(video),left)
    assert job.status=='done' and job.error is None
    assert job.result['analysis_contract']['handedness']==('left' if left else 'right')
    assert snapshots[-1]['analysis_contract']==job.result['analysis_contract']
    assert {k:v for k,v in job.result.items() if k!='analysis_contract'}==before==r
