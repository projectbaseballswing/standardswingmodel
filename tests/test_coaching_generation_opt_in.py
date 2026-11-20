"""No paid calls: deployment must explicitly enable automatic generation."""
import copy
import inspect
from unittest.mock import Mock

import pytest

from api.jobs import Job, JobManager
from feedback.coaching_review import PRIVATE_KEY, report_fingerprint, context_for, public_result
from tests.test_coaching_review import report, approved


@pytest.mark.parametrize('enabled,key', [(None, 'offline-key'), (False, 'offline-key'), (True, '')])
def test_no_implicit_generation_or_extended_call(monkeypatch, enabled, key):
    import api.jobs as jobs
    overall = Mock(side_effect=AssertionError('Unexpected paid generation'))
    extended = Mock(side_effect=AssertionError('Unexpected paid generation'))
    monkeypatch.setattr(jobs, 'generate_coaching', overall)
    monkeypatch.setattr(jobs, 'generate_extended_coaching', extended)
    manager = object.__new__(JobManager)
    manager.openai_api_key, manager.openai_model = key, 'offline'
    if enabled is not None:
        manager.coaching_enabled = enabled
    r = report(); before = report_fingerprint(r)
    job = Job('opt-in', {}, status='done', user_id='owner', result=r)
    manager._attach_overall_coaching(job)
    manager._attach_extended_coaching(job)
    overall.assert_not_called(); extended.assert_not_called()
    assert job.result['coaching'] is None and job.status == 'done'
    assert report_fingerprint(job.result) == before
    assert job.result[PRIVATE_KEY]['validation']['reason'] == (
        'not_configured' if enabled else 'generation_disabled')
    assert public_result(job.result, context=context_for('opt-in', 'owner'))['coaching'] is None


def test_disabled_extension_preserves_existing_review(monkeypatch):
    import api.jobs as jobs
    manager = object.__new__(JobManager)
    manager.openai_api_key = 'offline-key'
    manager.coaching_enabled = False
    r = report(); r[PRIVATE_KEY] = approved(r, context_for('a', 'u'))
    before = copy.deepcopy(r)
    generated = Mock(side_effect=AssertionError('Unexpected generation'))
    monkeypatch.setattr(jobs, 'generate_extended_coaching', generated)
    manager._attach_extended_coaching(Job('a', {}, status='done', user_id='u', result=r))
    assert r == before
    generated.assert_not_called()


def test_manager_default_and_application_setting_are_disabled(mock_client):
    assert inspect.signature(JobManager).parameters['coaching_enabled'].default is False
    assert mock_client.app.state.jobs.coaching_enabled is False
