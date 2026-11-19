"""Review lifecycle, public serialization and persistence. All data is synthetic.

Uses the repository disposable SQLite/FakeStorage fixtures. No OpenAI requests,
real accounts, live Supabase, or real A/B human approvals.
"""
import copy
import json
from pathlib import Path
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from api.database import SessionLocal, Swing
from api.jobs import Job, JobManager
from feedback.coaching_review import (
    PRIVATE_KEY, approve_review, capture_review, context_for, public_coaching,
    public_result, report_fingerprint,
)
from tests.auth_helpers import authenticate


def report():
    return json.loads((Path(__file__).resolve().parents[1]/'api/fixtures/analysis_sample.json').read_text(encoding='utf-8'))


def candidate():
    return {'overall_summary':'격리 테스트: 승인된 종합 문구',
            'overall_coach':'격리 테스트: 원본 구간 확인',
            'coach_feedback':{'problem':'측정된 차이를 확인합니다.',
                              'cause':'현재 분석만으로 원인을 확인하기 어렵습니다.',
                              'fix':'원본 영상을 확인합니다.',
                              'drill':'효과가 검증되지 않은 일반 연습 제안입니다.'},'parts':[]}


def pending(r,ctx,*,text=None,previous=None):
    return capture_review(r,{'candidate':candidate() if text is None else text},context=ctx,previous=previous)


def approved(r,ctx,*,previous=None):
    e=pending(r,ctx,previous=previous)
    return approve_review(r,e,context=ctx,reviewer_id='synthetic-test-reviewer',
                          note='Synthetic contract test only; not approval of saved GPT A/B.',
                          expected_candidate_sha256=e['candidate_sha256'],previous=previous)


def seed(client,r,identifier=None,when=None):
    identifier=identifier or uuid.uuid4().hex
    with SessionLocal.begin() as db:
        db.add(Swing(analysis_id=identifier,user_id=client.test_user_id,worker_id='review-tests',
                     status='done',result=r,recorded_at=when or datetime.now(timezone.utc)))
    return identifier


def test_capture_does_not_auto_approve_or_mutate_source():
    r=report();before=copy.deepcopy(r);ctx=context_for('analysis','owner');e=pending(r,ctx)
    assert r==before and e['status']=='review_required' and e['approval'] is None
    r[PRIVATE_KEY]=e;r['coaching']=candidate()
    public=public_result(r,context=ctx)
    assert public['coaching'] is None and not public['coaching_review']['display_allowed']
    assert PRIVATE_KEY not in public and 'candidate' not in public['coaching_review']
    assert r[PRIVATE_KEY]==e and r['coaching']==candidate()


def test_exact_reviewed_candidate_can_be_shown_but_tampering_cannot():
    r=report();ctx=context_for('analysis','owner');e=approved(r,ctx)
    c,m=public_coaching(r,e,context=ctx)
    assert c==candidate() and m['status']=='approved' and m['display_allowed']
    e['candidate']['overall_coach']='unreviewed replacement'
    assert public_coaching(r,e,context=ctx)[0] is None
    assert public_coaching(r,e,context=ctx)[1]['reason']=='candidate_changed'


@pytest.mark.parametrize('change',['report','owner','analysis','approval','scope','handedness','reference_id'])
def test_stale_or_forged_approval_is_withheld(change):
    r=report();ctx=context_for('analysis','owner');e=approved(r,ctx)
    if change=='report':r['overall']['score']=10
    if change=='owner':ctx=context_for('analysis','other-owner')
    if change=='analysis':ctx=context_for('other-analysis','owner')
    if change=='approval':e['approval']=None
    if change=='scope':e['scope']='full'
    if change=='handedness':r['handedness']='left'
    if change=='reference_id':r['reference_id']='another-reference'
    assert public_coaching(r,e,context=ctx)[0] is None


def test_blocked_and_failed_are_distinct_and_cannot_be_approved():
    r=report();ctx=context_for('analysis','owner');bad=candidate()
    bad['parts']=[{'key':'head_gaze','summary':'bad','keep_points':[],'improve_points':[]}]
    blocked=pending(r,ctx,text=bad)
    failed=capture_review(r,{},context=ctx)
    assert blocked['status']=='blocked' and failed['status']=='generation_failed'
    for e in [blocked,failed]:
        with pytest.raises(ValueError):
            approve_review(r,e,context=ctx,reviewer_id='test',note='test',expected_candidate_sha256=e['candidate_sha256'])


@pytest.mark.parametrize('corruption',['status_list','candidate_nan','candidate_list','approval_list','scope_dict'])
def test_malformed_private_json_does_not_break_analysis_http(mock_client,corruption):
    client=mock_client;r=report();identifier=uuid.uuid4().hex;ctx=context_for(identifier,client.test_user_id)
    envelope=approved(r,ctx)
    if corruption=='status_list':envelope['status']=[]
    if corruption=='candidate_nan':envelope['candidate']['unexpected']=float('nan')
    if corruption=='candidate_list':envelope['candidate']=[]
    if corruption=='approval_list':envelope['approval']=[]
    if corruption=='scope_dict':envelope['scope']={}
    r[PRIVATE_KEY]=envelope;seed(client,r,identifier)
    response=client.get(f'/api/analyses/{identifier}')
    assert response.status_code==200,response.text
    body=response.json()['result']
    assert body['coaching'] is None and body['coaching_review']['status']=='blocked'
    assert body['overall']['score']==r['overall']['score']


def test_nonfinite_evidence_blocks_review_without_raising_or_mutating_analysis():
    r=report();ctx=context_for('a','u');r['overall']['score']=float('nan')
    assert report_fingerprint(r) is None
    envelope=pending(r,ctx)
    assert envelope['status']=='blocked'
    assert public_coaching(r,envelope,context=ctx)[1]['reason']=='invalid_review_evidence'
    with pytest.raises(ValueError):
        approve_review(r,envelope,context=ctx,reviewer_id='test',note='test',expected_candidate_sha256=envelope['candidate_sha256'])
    bad=candidate();bad['unexpected']=float('nan')
    clean=capture_review(report(),{'candidate':bad},context=ctx)
    assert clean['status']=='blocked' and clean['candidate'] is None
    json.dumps(clean,allow_nan=False)  # Non-JSON output cannot poison a good result.


def test_thumbnail_and_3d_changes_do_not_change_score_evidence_binding():
    r=report();ctx=context_for('a','u');e=approved(r,ctx);h=report_fingerprint(r)
    r['thumbnail']={'path':'changed'};r['motion']={'phases':{}};r['comparison']={'unreviewed':'private'}
    assert report_fingerprint(r)==h
    r[PRIVATE_KEY]=e
    assert public_result(r,context=ctx)['coaching']==candidate()
    assert 'comparison' not in public_result(r,context=ctx)


@pytest.mark.parametrize('state',['legacy','pending','blocked','failed','approved'])
def test_http_detail_and_direct_coaching_only_expose_approved(mock_client,state):
    client=mock_client;r=report();identifier=uuid.uuid4().hex;ctx=context_for(identifier,client.test_user_id)
    r['coaching']=candidate()  # A raw dictionary alone must never authorize display.
    if state=='pending':r[PRIVATE_KEY]=pending(r,ctx)
    if state=='blocked':
        bad=candidate();bad['parts']=[{'key':'gaze','summary':'bad','keep_points':[],'improve_points':[]}]
        r[PRIVATE_KEY]=pending(r,ctx,text=bad)
    if state=='failed':r[PRIVATE_KEY]=capture_review(r,{},context=ctx)
    if state=='approved':r[PRIVATE_KEY]=approved(r,ctx)
    seed(client,r,identifier)
    response=client.get(f'/api/analyses/{identifier}?include_series=true')
    assert response.status_code==200,response.text
    result=response.json()['result']
    assert PRIVATE_KEY not in response.text and 'reviewer_id' not in response.text
    assert result['overall']['score']==r['overall']['score']
    direct=client.get(f'/api/analyses/{identifier}/coaching')
    if state=='approved':
        assert result['coaching']['overall_summary']==candidate()['overall_summary']
        assert direct.status_code==200 and result['coaching_review']['display_allowed'] is True
    else:
        assert result['coaching'] is None and direct.status_code==404
        assert candidate()['overall_summary'] not in response.text
    with SessionLocal() as db:assert db.get(Swing,identifier).result==r  # GET never rewrites legacy data.


def test_reviewed_result_survives_fresh_job_manager_read(mock_client):
    client=mock_client;r=report();identifier=uuid.uuid4().hex;ctx=context_for(identifier,client.test_user_id)
    r[PRIVATE_KEY]=approved(r,ctx);r['coaching']=None;seed(client,r,identifier)
    # A new manager instance gets the DB record rather than in-memory approval.
    manager=object.__new__(JobManager)
    restored=manager.get(identifier)
    assert public_result(restored.result,context=ctx)['coaching']==candidate()


def test_auth_remains_required_for_approved_coaching(mock_client):
    client=mock_client;r=report();identifier=uuid.uuid4().hex;ctx=context_for(identifier,client.test_user_id)
    r[PRIVATE_KEY]=approved(r,ctx);seed(client,r,identifier)
    client.headers.pop('Authorization')
    assert client.get(f'/api/analyses/{identifier}/coaching').status_code==401
    authenticate(client)
    assert client.get(f'/api/analyses/{identifier}/coaching').status_code==403


def test_jobs_capture_review_sink_and_failure_does_not_change_analysis(monkeypatch):
    import api.jobs as jobs
    manager=object.__new__(JobManager);manager.openai_api_key='fake';manager.openai_model='offline'
    def generate(r,*,review_sink,**kwargs):review_sink.update(candidate=candidate(),validation={});return None
    monkeypatch.setattr(jobs,'generate_coaching',generate)
    r=report();h=report_fingerprint(r);job=Job('a',{},status='done',user_id='u',result=r)
    manager._attach_overall_coaching(job)
    assert job.result['coaching'] is None and job.result[PRIVATE_KEY]['status']=='review_required'
    assert report_fingerprint(job.result)==h and job.status=='done'
    def fail(*args,**kwargs):raise RuntimeError('fake provider failure')
    monkeypatch.setattr(jobs,'generate_coaching',fail)
    manager._attach_overall_coaching(job)
    assert job.result[PRIVATE_KEY]['status']=='generation_failed' and report_fingerprint(job.result)==h


def test_extended_text_invalidates_approval(monkeypatch):
    import api.jobs as jobs
    manager=object.__new__(JobManager);manager.openai_api_key='fake';manager.openai_model='offline'
    r=report();ctx=context_for('a','u');r[PRIVATE_KEY]=approved(r,ctx)
    def generate(r,*,review_sink,**kwargs):review_sink['candidate']={'joints':[],'phases':[]};return None
    monkeypatch.setattr(jobs,'generate_extended_coaching',generate)
    job=Job('a',{},status='done',user_id='u',result=r)
    manager._attach_extended_coaching(job)
    assert job.result[PRIVATE_KEY]['status']=='review_required'
    assert job.result[PRIVATE_KEY]['approval'] is None and job.result['coaching'] is None


def test_extended_rejected_fields_are_not_silently_dropped_before_review(monkeypatch):
    import api.jobs as jobs
    manager=object.__new__(JobManager);manager.openai_api_key='fake';manager.openai_model='offline'
    r=report();ctx=context_for('a','u');r[PRIVATE_KEY]=approved(r,ctx)
    def generate(r,*,review_sink,**kwargs):
        review_sink['candidate']={'joints':[],'phases':[], 'unapproved_extra':'must be rejected'}
    monkeypatch.setattr(jobs,'generate_extended_coaching',generate)
    job=Job('a',{},status='done',user_id='u',result=r)
    manager._attach_extended_coaching(job)
    assert job.result[PRIVATE_KEY]['status']=='blocked'
    assert job.result[PRIVATE_KEY]['approval'] is None
    assert public_result(job.result,context=ctx)['coaching'] is None


def test_extended_merge_preserves_other_fields_and_rejects_stale_revision(mock_client):
    client=mock_client;r=report();identifier=uuid.uuid4().hex;ctx=context_for(identifier,client.test_user_id)
    original_hash=report_fingerprint(r)
    seed(client,r,identifier)
    # A concurrent writer adds unrelated motion/comparison data after the job snapshot.
    with SessionLocal.begin() as db:
        row=db.get(Swing,identifier);current=copy.deepcopy(row.result)
        current['motion']={'preserve':True};current['comparison']={'preserve':True};row.result=current
    job=Job(identifier,{},status='done',user_id=client.test_user_id,result=copy.deepcopy(r))
    job.result[PRIVATE_KEY]=pending(r,ctx)
    manager=object.__new__(JobManager);manager._merge_save_coaching(job)
    with SessionLocal() as db:
        stored=db.get(Swing,identifier).result
        assert stored['motion']=={'preserve':True} and stored['comparison']=={'preserve':True}
        assert stored[PRIVATE_KEY]['status']=='review_required' and report_fingerprint(stored)==original_hash
    with SessionLocal.begin() as db:
        row=db.get(Swing,identifier);changed=copy.deepcopy(row.result)
        changed['overall']['score']=11;row.result=changed
    job.result[PRIVATE_KEY]['created_at']='must-not-replace-newer-result'
    manager._merge_save_coaching(job)
    with SessionLocal() as db:
        stored=db.get(Swing,identifier).result
        assert stored['overall']['score']==11
        assert stored[PRIVATE_KEY]['created_at']!='must-not-replace-newer-result'


def test_comparison_approval_bound_to_exact_previous_record(mock_client):
    client=mock_client;prev=report();cur=report();now=datetime.now(timezone.utc)
    previous_id=seed(client,prev,when=now-timedelta(days=1));identifier=uuid.uuid4().hex
    ctx=context_for(identifier,client.test_user_id,previous_analysis_id=previous_id,previous=prev)
    cur['comparison']={'previous_analysis_id':previous_id,PRIVATE_KEY:approved(cur,ctx,previous=prev)}
    seed(client,cur,identifier,when=now)
    url=f'/api/users/{client.test_user_id}/analyses/{identifier}/comparison'
    body=client.get(url).json();assert body['coaching']['overall_summary']==candidate()['overall_summary']
    assert body['coaching_review']['status']=='approved'
    with SessionLocal.begin() as db:
        old=db.get(Swing,previous_id);changed=copy.deepcopy(old.result);changed['overall']['score']=10;old.result=changed
    body=client.get(url).json();assert body['coaching'] is None
    assert body['coaching_review']['reason']=='stale_review_context'
