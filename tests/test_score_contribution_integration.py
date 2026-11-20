"""Offline PR86/coaching compatibility. No inference or remote services."""
import copy
from types import SimpleNamespace

import numpy as np
import pytest

from api.schemas import AnalysisReport
from feedback.compare_v2 import SwingComparisonV2
from feedback.coaching_compact import compact_coaching_input, expand_coaching_input
from feedback.coaching_evidence import build_evidence_input
from feedback.coaching_policy import validate_coaching_output
from feedback.coaching_review import capture_review, public_result, context_for, PRIVATE_KEY
from tests.test_coaching_compact import sample
from tests.test_coaching_policy import coaching, codes


def contributions():
    return [{'key':'rear_arm','name':'오른쪽 팔','share':.8,'score':20,'reliability':'low'},
            {'key':'lead_arm','name':'왼쪽 팔','share':.2,'score':70,'reliability':'high'}]


def test_main_calculation_includes_low_without_changing_distance_or_scores():
    comparison=SwingComparisonV2.__new__(SwingComparisonV2)
    comparison.model=SimpleNamespace(feature_names=['rear_elbow_angle','lead_elbow_angle'])
    comparison.diff_z={'swing':np.array([[2.,1.],[2.,1.]])}
    groups=[dict(c,available=True) for c in contributions()]
    before=copy.deepcopy(groups);distance=comparison._overall_distance()
    rows=comparison._score_contributions(groups)
    assert rows==contributions() and groups==before
    assert comparison._overall_distance()==distance==pytest.approx(np.sqrt(2.5))


@pytest.mark.parametrize('scope',['overall','full'])
def test_low_share_is_preserved_but_never_promoted_to_correction(scope):
    report=sample();baseline=build_evidence_input(report,scope=scope)
    report['overall']['score_contributions']=contributions();before=copy.deepcopy(report)
    evidence=build_evidence_input(report,scope=scope)
    assert evidence['priority_candidates']==baseline['priority_candidates']
    assert evidence['allowed']==baseline['allowed']
    assert all(c['part']!='rear_arm' for c in evidence['priority_candidates'])
    assert [c['share'] for c in evidence['score_contributions']['rows']]==[.8,.2]
    assert evidence['score_contributions']['rows'][0]['reliability']=='low'
    assert expand_coaching_input(compact_coaching_input(evidence))==evidence
    assert report==before
    parsed=AnalysisReport.model_validate(report)
    assert parsed.overall.score==report['overall']['score']
    assert parsed.overall.score_contributions[0].share==.8


def test_old_report_has_no_invented_contributions():
    report=sample()
    assert 'score_contributions' not in build_evidence_input(report)
    assert AnalysisReport.model_validate(report).overall.score_contributions==[]


def test_pr87_feature_shares_exclude_low_and_do_not_reorder_evidence():
    comparison=SwingComparisonV2.__new__(SwingComparisonV2)
    comparison.reliability='high'
    comparison.model=SimpleNamespace(feature_names=['rear_elbow_angle','lead_elbow_angle','hand_y_from_shoulder'])
    comparison.diff_z={'swing':np.array([[20.,1.,2.]])}
    shares=comparison._feature_part_shares()
    assert shares=={'rear_elbow_angle':None,'lead_elbow_angle':.2,'hand_y_from_shoulder':.8}
    report=sample();before=build_evidence_input(report)
    for joint in report['joints']:
        joint['contribution']=shares.get(joint['key'])
    evidence=build_evidence_input(report)
    assert evidence['priority_candidates']==before['priority_candidates']
    assert expand_coaching_input(compact_coaching_input(evidence))==evidence
    allowed={j['key']:j for p in evidence['parts'] for j in p['features']}
    assert allowed['lead_elbow_angle']['part_difference_share']==.2
    assert 'rear_elbow_angle' not in allowed


def test_invalid_shares_and_duplicate_keys_are_not_recomputed():
    report=sample();report['overall']['score_contributions']=[
        *contributions(),dict(contributions()[0]),
        {'key':[],'share':.1}, {'key':'torso','share':float('nan'),'reliability':'high'}]
    evidence=build_evidence_input(report)['score_contributions']
    assert [r['share'] for r in evidence['rows']]==[.2]  # Never renormalize to 1.
    assert len(evidence['excluded'])==4


def test_contribution_context_never_bypasses_review():
    report=sample();report['overall']['score_contributions']=contributions()
    ctx=context_for('synthetic-contribution','isolated-user')
    envelope=capture_review(report,{'candidate':coaching()},context=ctx)
    report[PRIVATE_KEY]=envelope
    public=public_result(report,context=ctx)
    assert public['overall']['score_contributions']==contributions()
    assert public['coaching'] is None
    assert public['coaching_review']['display_allowed'] is False
    assert PRIVATE_KEY not in public


@pytest.mark.parametrize('text',[
    '몸통 영향도 60%이므로 종합점수를 20점 낮췄어요.',
    '오른쪽 팔 비중이 높으므로 먼저 교정하세요.',
])
def test_contribution_misinterpretation_requires_review(text):
    report=sample();report['overall']['score_contributions']=contributions()
    candidate=coaching();candidate['overall_summary']=text
    result=validate_coaching_output(candidate,build_evidence_input(report))
    assert 'contribution_interpretation_review' in codes(result)
    assert not result['auto_publish_allowed']


def test_relative_share_explanation_is_not_a_70_30_formula_violation():
    candidate=coaching();candidate['overall_summary']='자세 계산의 부위별 차이 비중은 80%예요. 종합점수의 감점량은 아니에요.'
    result=validate_coaching_output(candidate,build_evidence_input(sample()))
    assert 'score_formula_conflict' not in codes(result)
    assert 'contribution_interpretation_review' not in codes(result)
    assert result['status']=='review_required'  # Meaning still needs human review.
