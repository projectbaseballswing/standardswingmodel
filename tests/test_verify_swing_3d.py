"""Safety guards and packet validation only; no live requests or inference."""
import argparse
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts import verify_swing_3d as verify
from tests.pose3d_fixture_builder import packet


@pytest.mark.parametrize('url', [
    'https://user:secret@example.com', 'http://example.com',
    'https://example.com/?token=secret', 'https://example.com/#secret',
    'https://example.com/api', 'file:///local',
])
def test_remote_transport_and_credential_guards(url):
    with pytest.raises(verify.VerificationError):
        verify.validate_base_url(url)


def test_loopback_and_https_base_allowed():
    assert verify.validate_base_url('http://127.0.0.1:8000/') == 'http://127.0.0.1:8000'
    assert verify.validate_base_url('https://example.com') == 'https://example.com'


def test_case_handedness_is_explicit_not_filename():
    value = verify.parse_case('left=some=video.mp4')
    assert value.handedness == 'left' and value.path == Path('some=video.mp4')
    with pytest.raises(argparse.ArgumentTypeError):
        verify.parse_case('some-left-player.mp4')


@pytest.mark.parametrize('existing', [False, True])
def test_opt_in_and_existing_receipt_stop_before_network(tmp_path, monkeypatch, existing):
    output = tmp_path / 'report.json'
    if existing:
        output.write_text('original failed receipt', encoding='utf-8')
    def should_not_run(*args):
        pytest.fail('Safety guard allowed verify/network execution')
    monkeypatch.setattr(verify, 'verify', should_not_run)
    args = ['--base-url', 'http://localhost:8000', '--case', 'left=fixture.mp4',
            '--output', str(output)]
    if existing:
        args.append('--allow-create-test-data')
    assert verify.main(args) == 1
    if existing:
        assert output.read_text('utf-8') == 'original failed receipt'
    else:
        assert not output.exists()


@pytest.mark.parametrize('mock,version', [(True, '0.2-draft'), (False, '0.1')])
def test_mock_or_old_model_health_never_creates_accounts(monkeypatch, mock, version):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.method == 'GET' and request.url.path == '/api/health'
        return httpx.Response(200, json={'mock': mock, 'model_version': version})
    client_type = httpx.Client
    monkeypatch.setattr(verify.httpx, 'Client', lambda **kwargs:
                        client_type(**kwargs, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(verify, 'inspect_video', lambda _: {})
    args = SimpleNamespace(base_url='http://localhost:8000', case=[verify.Case('left', Path('x.mp4'))])
    report = {'checks': [], 'created_test_accounts': [], 'uploads': []}
    with pytest.raises(verify.VerificationError, match='health_real_model02'):
        verify.verify(args, report, lambda: None)
    assert len(requests) == 1 and not report['created_test_accounts']


@pytest.fixture
def synthetic_packet():
    clip = packet(7, 60, True)
    envelope = {'analysis_id': clip['id'], 'user_id': 'synthetic-owner',
                'contract_version': 'EXP008-pose3d-v1', 'status': 'ready',
                'frame_count': clip['frame_count'], 'clip': clip}
    metadata = {'sha256': clip['source_provenance']['source_video_sha256'],
                'frames': clip['frame_count'], 'pts': [i / 60 for i in range(7)]}
    return envelope, metadata


def test_timestamp_identity_and_processing_guards(synthetic_packet):
    envelope, metadata = synthetic_packet
    case = verify.Case('left', Path('unrelated-name.mp4'))
    def check(value):
        verify.validate_packet(value, envelope['analysis_id'], 'synthetic-owner', case, metadata)
    check(envelope)
    for mutation in ('identity', 'pts', 'smoothing', 'nulls'):
        modified = copy.deepcopy(envelope)
        clip = modified['clip']
        if mutation == 'identity':
            clip['analysis_id'] = 'another-upload'
        elif mutation == 'pts':
            clip['timestamps_s'][2] += .001
        elif mutation == 'smoothing':
            clip['final_display_data']['processing']['smoothing_passes'] = 2
        else:
            clip['final_display_data']['display_orientation']['frames'][0]['positions'][0] = None
        with pytest.raises(verify.VerificationError):
            check(modified)


def test_unexpected_exception_text_never_reaches_output(tmp_path, monkeypatch, capsys):
    secret = 'secret-token-must-not-be-in-report'
    def broken(*args):
        raise RuntimeError(secret)
    monkeypatch.setattr(verify, 'verify', broken)
    output = tmp_path / 'report.json'
    assert verify.main(['--base-url', 'http://localhost:8000', '--case', 'right=fixture.mp4',
                        '--output', str(output), '--allow-create-test-data']) == 1
    assert secret not in output.read_text('utf-8') and secret not in capsys.readouterr().out
    assert json.loads(output.read_text('utf-8'))['error_type'] == 'RuntimeError'
