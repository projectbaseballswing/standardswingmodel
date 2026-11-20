"""Shared API/Flutter notice contract. Only isolated SQLite and synthetic text."""
import copy
import json
from pathlib import Path
import uuid

import pytest

from api.database import SessionLocal, Swing
from feedback.coaching_review import PRIVATE_KEY, capture_review, context_for, public_result
from tests.test_coaching_review import report, candidate, pending, approved, seed

CASES = json.loads((Path(__file__).resolve().parents[1] /
    'frontend/test/fixtures/coaching_review_notices.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', CASES)
def test_http_review_metadata_matches_flutter_notice_contract(mock_client, case):
    r = report(); r.pop('coaching', None)
    identifier = uuid.uuid4().hex
    ctx = context_for(identifier, mock_client.test_user_id)
    expected = CASES[case]['review']
    if case == 'pending':
        r[PRIVATE_KEY] = pending(r, ctx)
    elif case == 'blocked':
        bad = candidate()
        bad['parts'] = [{'key': 'head_gaze', 'summary': 'bad', 'keep_points': [], 'improve_points': []}]
        r[PRIVATE_KEY] = pending(r, ctx, text=bad)
    elif case == 'approved':
        r[PRIVATE_KEY] = approved(r, ctx)
    elif case != 'not_generated':
        r[PRIVATE_KEY] = capture_review(r, {}, context=ctx, failure_reason=expected['reason'])
    # An unapproved raw coaching dictionary must never authorize display.
    if case != 'not_generated':
        r['coaching'] = candidate()
    seed(mock_client, r, identifier)
    response = mock_client.get(f'/api/analyses/{identifier}')
    assert response.status_code == 200, response.text
    public = response.json()['result']
    assert public['coaching_review'] == expected
    assert public['overall']['score'] == r['overall']['score']
    assert PRIVATE_KEY not in public
    if case == 'approved':
        assert public['coaching']['overall_summary'] == candidate()['overall_summary']
    else:
        assert public['coaching'] is None and not public['coaching_review']['display_allowed']
        assert candidate()['overall_summary'] not in response.text
    assert mock_client.get(f'/api/analyses/{identifier}/coaching').status_code == (200 if case == 'approved' else 404)
    with SessionLocal() as db:
        assert db.get(Swing, identifier).result == r  # No legacy data rewrite.


@pytest.mark.parametrize('validation', [
    None, False, 42, [], 'private-provider-detail', {},
    {'reason': None}, {'reason': False}, {'reason': 7},
    {'reason': []}, {'reason': {}}, {'reason': 'private-provider-detail'},
    {'reason': 'approved'},
])
def test_malformed_or_unknown_failure_reason_is_not_published(validation):
    r = report(); ctx = context_for('a', 'u')
    envelope = capture_review(r, {}, context=ctx)
    envelope['validation'] = validation
    r[PRIVATE_KEY] = envelope
    before = copy.deepcopy(r)
    public = public_result(r, context=ctx)
    assert public['coaching_review'] == CASES['not_generated']['review']
    assert public['coaching'] is None and PRIVATE_KEY not in public
    assert r == before


def test_missing_reason_uses_basic_notice_and_context_checks_still_apply():
    r = report(); ctx = context_for('a', 'u')
    r[PRIVATE_KEY] = capture_review(r, {}, context=ctx, failure_reason='generation_disabled')
    r[PRIVATE_KEY].pop('validation')
    assert public_result(r, context=ctx)['coaching_review'] == CASES['not_generated']['review']
    public = public_result(r, context=context_for('a', 'another-owner'))
    assert public['coaching'] is None and not public['coaching_review']['display_allowed']
    assert public['coaching_review']['reason'] == 'stale_review_context'
