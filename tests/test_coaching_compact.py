"""Offline 3-E evidence preservation; no network or new model inference."""
import copy
import json
from pathlib import Path
import pytest

from feedback.coaching_evidence import build_evidence_input,phase_evidence,measured_range
from feedback.coaching_compact import compact_coaching_input,expand_coaching_input
from feedback.llm_coach import build_comparison_input

ROOT=Path(__file__).resolve().parents[1]
def sample():return json.loads((ROOT/'api/fixtures/analysis_sample.json').read_text(encoding='utf-8'))

@pytest.mark.parametrize('scope',['overall','full'])
def test_lossless_roundtrip_all_fields_and_no_input_mutation(scope):
    r=sample();before=copy.deepcopy(r);e=build_evidence_input(r,scope=scope);snapshot=copy.deepcopy(e)
    packed=compact_coaching_input(e);restored=expand_coaching_input(packed)
    assert restored==e==snapshot and r==before
    assert len(json.dumps(packed,ensure_ascii=False))<len(json.dumps(e,ensure_ascii=False))*.65
    assert packed['evidence']['score_basis']==e['score_basis']
    assert packed['evidence']['excluded']==e['excluded']

def test_opposite_aggregate_signs_are_not_an_invalid_measurement():
    e=build_evidence_input(sample())
    match=next(o for o in e['observations'] if o['joint']=='hip_shoulder_separation' and o['phase']=='follow')
    assert match['diff']==-.7 and match['z_score']==.05
    assert match['level']=='good'

def test_rom_restored_without_inventing_z_or_level():
    e=build_evidence_input(sample())
    j=next(j for p in e['parts'] for j in p['features'] if j['key']=='lead_elbow_angle')
    original=next(j for j in sample()['joints'] if j['key']=='lead_elbow_angle')['range_of_motion']
    assert j['range_of_motion']=={k:original[k] for k in ('user','reference','diff')}
    assert 'z_score' not in j['range_of_motion']
    assert measured_range({'user':10,'reference':20,'diff':999}) is None
    assert measured_range({'user':float('nan'),'reference':20,'diff':-10}) is None

def test_comparison_payload_lossless():
    a=sample();b=sample();b['overall']['score']=57.3
    for scope in ('overall','full'):
        e=build_comparison_input(a,b,scope=scope)
        assert expand_coaching_input(compact_coaching_input(e))==e

def test_empty_and_missing_evidence_roundtrip():
    for r in ({}, {'overall':{'available':False},'joints':[]}):
        e=build_evidence_input(r)
        assert expand_coaching_input(compact_coaching_input(e))==e

def test_low_reliability_never_reintroduced_by_compaction():
    e=build_evidence_input(sample(),scope='full');packed=compact_coaching_input(e)
    assert 'rear_elbow_angle' not in packed['joint_table']
    assert any(x['key']=='rear_elbow_angle' for x in packed['evidence']['excluded'])
    assert 'rear_elbow_angle' not in expand_coaching_input(packed)['allowed']['joints']

def test_rare_phase_problem_retained_even_when_part_score_good():
    r=sample();e=build_evidence_input(r);packed=compact_coaching_input(e);restored=expand_coaching_input(packed)
    rear=[o for o in restored['observations'] if o['part']=='rear_leg']
    assert any(o['phase']=='stride' and o['level']=='good' for o in rear)
    assert any(o['phase']=='swing' and o['level']=='caution' for o in rear)


@pytest.mark.parametrize('entry',['overall','extended','comparison'])
def test_generation_uses_compact_wire_but_validates_full_evidence(monkeypatch,entry):
    from feedback import llm_coach as llm
    captured=[]
    candidate={'overall_summary':'스트라이드 구간을 원본에서 확인하세요.',
               'overall_coach':'현재 분석만으로 원인을 확인하기 어렵습니다.',
               'coach_feedback':{'problem':'손 높이 차이가 측정됐습니다.','cause':'원인 미확인',
                                 'fix':'원본 확인 후 편안한 범위에서 시도하세요.','drill':'일반적인 느린 동작 연습입니다.'},
               'parts':[]}
    if entry=='extended':candidate={'joints':[],'phases':[]}
    def fake(**kwargs):
        captured.append(kwargs['payload'])
        return candidate
    monkeypatch.setattr(llm,'_call_openai',fake)
    sink={};r=sample()
    if entry=='overall':
        value=llm.generate_coaching(r,api_key='synthetic-not-a-key',model='offline',review_sink=sink)
        expected=llm.build_llm_input(r)
    elif entry=='extended':
        value=llm.generate_extended_coaching(r,api_key='synthetic-not-a-key',model='offline',review_sink=sink)
        expected=llm.build_llm_input(r,scope='full')
    else:
        previous=sample()
        value=llm.generate_comparison_coaching(r,previous,api_key='synthetic-not-a-key',model='offline',review_sink=sink)
        expected=llm.build_comparison_input(r,previous)
    assert value is None and len(captured)==1
    assert expand_coaching_input(captured[0])==expected
    assert sink['candidate']==candidate and sink['validation']['auto_publish_allowed'] is False
