"""Opt-in real-video API verification; creates labelled accounts and uploads.

Never provisions/migrates/deletes remote resources or starts a server. Passwords,
tokens, signed URLs and coordinate payloads stay in memory. Use a fresh report
path per intentional run; an existing receipt prevents duplicate uploads.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
from pathlib import Path
import re
import secrets
import statistics
import time
from urllib.parse import urljoin, urlsplit

import httpx


class VerificationError(Exception):
    """Internal fixed check identifiers only; never server response text."""


def require(condition, check):
    if not condition:
        raise VerificationError(check)


@dataclass(frozen=True)
class Case:
    handedness: str
    path: Path


def parse_case(value):
    handedness, separator, path = value.partition('=')
    if not separator or handedness not in ('left', 'right') or not path:
        raise argparse.ArgumentTypeError('Use left=path.mp4 or right=path.mp4')
    return Case(handedness, Path(path))


def validate_base_url(value):
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme in ('http', 'https') and parsed.hostname
                 and parsed.username is None and parsed.password is None
                 and parsed.path in ('', '/') and not parsed.query and not parsed.fragment)
        valid = valid and (parsed.scheme == 'https'
                           or parsed.hostname in ('127.0.0.1', 'localhost', '::1'))
        _ = parsed.port
    except ValueError:
        valid = False
    require(valid, 'base_url_requires_https_or_loopback_without_credentials')
    return value.rstrip('/')


def inspect_video(path):
    """Read actual decoded timestamps; no inference or FPS inference from names."""
    import cv2
    require(path.is_file() and path.suffix.lower() == '.mp4', 'input_mp4_required')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    cap = cv2.VideoCapture(str(path.resolve()))
    times = []
    try:
        require(cap.isOpened(), 'input_decode_open')
        nominal_fps = cap.get(cv2.CAP_PROP_FPS)
        while True:
            ok, _ = cap.read()
            if not ok:
                break
            times.append(float(cap.get(cv2.CAP_PROP_POS_MSEC)) / 1000)
    finally:
        cap.release()
    require(bool(times) and all(math.isfinite(t) for t in times), 'input_finite_pts')
    intervals = [b - a for a, b in zip(times, times[1:])]
    require(all(dt > 0 for dt in intervals), 'input_increasing_pts')
    return {'sha256': digest.hexdigest(), 'frames': len(times), 'pts': times,
            'nominal_fps': nominal_fps if math.isfinite(nominal_fps) else None,
            'effective_pts_fps': 1 / statistics.median(intervals) if intervals else None}


def validate_packet(packet, analysis_id, owner, case, metadata):
    clip = packet['clip']
    require(packet['analysis_id'] == analysis_id and packet['user_id'] == owner
            and packet['contract_version'] == 'EXP008-pose3d-v1'
            and packet['status'] == 'ready', 'pose_envelope_identity')
    require(clip['id'] == analysis_id and clip['analysis_id'] == analysis_id
            and clip['data_kind'] == 'analysis'
            and clip['source_provenance']['source_video_sha256'] == metadata['sha256'],
            'pose_upload_identity')
    require(clip['handedness'] == case.handedness
            and clip['mirrored_input'] is (case.handedness == 'left')
            and clip['source_oriented'] is True, 'pose_source_restoration')
    times = clip['timestamps_s']
    require(len(times) == clip['frame_count'] == packet['frame_count'] == metadata['frames']
            and all(math.isfinite(t) for t in times), 'pose_frame_count')
    origin = metadata['pts'][0]
    require(all(abs(t - (source - origin)) < 1e-6
                for t, source in zip(times, metadata['pts'])), 'pose_decoded_timestamp_alignment')
    require(len(clip['raw_estimation']['decoded_pts_s']) == len(times)
            and all(abs(a - b) < 1e-6 for a, b in zip(
                clip['raw_estimation']['decoded_pts_s'], metadata['pts'])), 'pose_raw_pts_preserved')
    final = clip['final_display_data']
    require(final['binding']['clip_id'] == analysis_id
            and final['binding']['source_sha256'] == metadata['sha256']
            and final['processing']['smoothing_passes'] == 1
            and final['processing']['interpolation'] is False, 'pose_processing_once')
    raw, display = final['raw_orientation']['frames'], final['display_orientation']['frames']
    require(len(raw) == len(display) == len(times), 'pose_display_frame_count')
    for before, after, t in zip(raw, display, times):
        require(before['timestamp_s'] == after['timestamp_s'] == t
                and before['p2'] == after['p2'], 'pose_display_time_and_p2')
        for field in ('positions', 'feet'):
            require(len(before[field]) == len(after[field])
                    and [p is None for p in before[field]] == [p is None for p in after[field]],
                    'pose_null_mask_preserved')


def save(path, report):
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                    encoding='utf-8')


def reserve_output(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation before any network mutation is also a concurrent-run guard.
    with path.open('x', encoding='utf-8') as stream:
        stream.write('{"status":"preflight"}\n')


def verify(args, report, record):
    base = validate_base_url(args.base_url)
    cases = [(case, inspect_video(case.path)) for case in args.case]
    tokens = []

    def check(name, passed, http_status=None):
        row = {'name': name, 'passed': bool(passed)}
        if http_status is not None:
            row['http_status'] = http_status
        report['checks'].append(row)
        record()
        require(passed, name)

    # Library logs could include signed URL query strings; keep reports allowlisted.
    for logger in ('httpx', 'httpcore'):
        logging.getLogger(logger).setLevel(logging.WARNING)
    with httpx.Client(base_url=base, trust_env=False, timeout=60, follow_redirects=False) as client:
        health = client.get('/api/health')
        check('health_http', health.status_code == 200, health.status_code)
        health_body = health.json()
        report['mock'] = health_body.get('mock') if type(health_body.get('mock')) is bool else None
        check('health_real_model02', health_body.get('mock') is False
              and str(health_body.get('model_version', '')).startswith('0.2'))
        report['health_model_version'] = health_body['model_version']
        try:
            for label in ('owner', 'other'):
                user = 'swing3d-e2e-' + secrets.token_hex(8)
                password = secrets.token_urlsafe(24)
                account = {'user_id': user, 'role': label, 'registration': 'attempted'}
                report['created_test_accounts'].append(account)
                record()
                response = client.post('/api/register', json={
                    'id': user, 'password': password, 'email': user + '@example.com', 'nickname': user})
                check(label + '_register', response.status_code == 200, response.status_code)
                account['registration'] = 'confirmed'
                response = client.post('/api/login', json={'id': user, 'password': password})
                password = None
                check(label + '_login', response.status_code == 200, response.status_code)
                login = response.json()
                token = login.get('access_token')
                check(label + '_bearer', isinstance(token, str) and bool(token)
                      and login.get('user') == user and login.get('token_type', '').lower() == 'bearer')
                tokens.append((user, token))
            owner, token = tokens[0]
            ha = {'Authorization': 'Bearer ' + token}
            hb = {'Authorization': 'Bearer ' + tokens[1][1]}
            for index, (case, metadata) in enumerate(cases, 1):
                prefix = 'case_' + str(index)
                item = {'case': index, 'handedness': case.handedness, 'status': 'upload_attempted',
                        **{k: v for k, v in metadata.items() if k != 'pts'}}
                report['uploads'].append(item)
                record()
                with case.path.open('rb') as stream:
                    response = client.post('/api/analyses', headers=ha,
                        data={'handedness': case.handedness, 'user_id': owner},
                        files={'video': ('case-' + str(index) + '.mp4', stream, 'video/mp4')})
                check(prefix + '_upload', response.status_code == 202, response.status_code)
                aid = response.json()['analysis_id']
                require(isinstance(aid, str) and re.fullmatch('[a-f0-9]{32}', aid), 'analysis_id_format')
                item.update(analysis_id=aid, status='processing')
                record()
                endpoint = '/api/analyses/' + aid
                deadline = time.monotonic() + args.timeout_seconds
                while True:
                    response = client.get(endpoint, headers=ha, params={'include_series': 'true'})
                    require(response.status_code == 200, 'analysis_query_http')
                    analysis = response.json()
                    if analysis['status'] in ('done', 'failed'):
                        break
                    require(time.monotonic() < deadline, 'analysis_poll_timeout')
                    time.sleep(.5)
                check(prefix + '_score_done', analysis['status'] == 'done')
                result = analysis['result']
                check(prefix + '_score_model02', str(result.get('model_version', '')).startswith('0.2')
                      and all(key in result for key in ('overall', 'joints', 'phases', 'speed')))
                while True:
                    response = client.get(endpoint + '/pose-3d', headers=ha)
                    if response.status_code != 202:
                        break
                    require(time.monotonic() < deadline, 'pose_poll_timeout')
                    time.sleep(.5)
                check(prefix + '_pose_ready', response.status_code == 200, response.status_code)
                packet = response.json()
                validate_packet(packet, aid, owner, case, metadata)
                check(prefix + '_pose_identity_pts_masks', True)
                for suffix in ('', '/pose-3d', '/video', '/overall', '/joints', '/phases'):
                    for label, headers, expected in (('unauthenticated', {}, 401),
                            ('invalid_token', {'Authorization': 'Bearer invalid-token'}, 401),
                            ('other_owner', hb, 403)):
                        response = client.get(endpoint + suffix, headers=headers)
                        check(prefix + label + (suffix or '/analysis'), response.status_code == expected,
                              response.status_code)
                again = client.get(endpoint + '/pose-3d', headers=ha)
                check(prefix + '_stored_requery', again.status_code == 200
                      and again.json()['clip'] == packet['clip'])
                history_path = '/api/users/' + owner + '/swings'
                history = client.get(history_path, headers=ha)
                check(prefix + '_own_history', history.status_code == 200
                      and aid in [row['analysis_id'] for row in history.json()['items']])
                for headers, expected in (({}, 401), (hb, 403)):
                    response = client.get(history_path, headers=headers)
                    check(prefix + '_history_' + str(expected), response.status_code == expected,
                          response.status_code)
                video = client.get(endpoint + '/video', headers=ha)
                check(prefix + '_video_url', video.status_code == 200, video.status_code)
                url = urljoin(base + '/', video.json()['url'])
                parsed = urlsplit(url)
                require(parsed.username is None and parsed.password is None
                        and (parsed.scheme == 'https' or (parsed.scheme == 'http'
                             and parsed.netloc == urlsplit(base).netloc)), 'video_url_transport')
                # No app bearer header is forwarded to a signed Storage URL.
                with httpx.Client(trust_env=False, timeout=60, follow_redirects=False) as downloader:
                    with downloader.stream('GET', url, headers={'Range': 'bytes=0-1023'}) as streamed:
                        check(prefix + '_stored_video_read', streamed.status_code in (200, 206),
                              streamed.status_code)
                        require(bool(next(streamed.iter_bytes(chunk_size=1024), b'')), 'stored_video_empty')
                item.update(status='passed', model_version=result['model_version'])
                record()
            for label, (user, token) in zip(('owner', 'other'), tokens):
                headers = {'Authorization': 'Bearer ' + token}
                response = client.post('/api/logout', headers=headers)
                check(label + '_logout', response.status_code == 200, response.status_code)
                response = client.get('/api/users/' + user + '/swings', headers=headers)
                check(label + '_revoked', response.status_code == 401, response.status_code)
            report['status'] = 'passed'
        finally:
            # Revoke only sessions this process created. Never delete accounts/data.
            report['session_cleanup'] = []
            for user, token in tokens:
                try:
                    response = client.post('/api/logout', headers={'Authorization': 'Bearer ' + token})
                    cleaned = response.status_code in (200, 401)
                except Exception:
                    cleaned = False
                report['session_cleanup'].append({'user_id': user, 'revoked_or_invalid': cleaned})
            record()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--case', action='append', required=True, type=parse_case)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--timeout-seconds', type=float, default=300)
    parser.add_argument('--allow-create-test-data', action='store_true')
    args = parser.parse_args(argv)
    report = {'status': 'preflight', 'started_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'live API, real uploaded videos, model 0.2 and private 3D API',
              'storage_implementation': 'not independently audited by this HTTP tool',
              'required_mock': False, 'mock': None, 'created_test_accounts': [], 'uploads': [], 'checks': [],
              'remote_ddl_performed': False, 'test_data_deleted': False,
              'actual_pose_accuracy_measured': False}
    reserved = False
    try:
        require(args.allow_create_test_data, 'allow_create_test_data_required')
        require(math.isfinite(args.timeout_seconds) and 0 < args.timeout_seconds <= 3600,
                'timeout_must_be_0_to_3600_seconds')
        validate_base_url(args.base_url)
        reserve_output(args.output)
        reserved = True
        report['status'] = 'running'
        verify(args, report, lambda: save(args.output, report))
    except Exception as exc:
        report['status'] = 'failed'
        report['error_type'] = type(exc).__name__
        if isinstance(exc, VerificationError):
            report['failed_check'] = str(exc)
    finally:
        if reserved:
            try:
                save(args.output, report)
            except Exception as exc:
                report['status'] = 'failed'
                report['error_type'] = type(exc).__name__
                report['failed_check'] = 'receipt_write_failed'
    # Reports contain only allowlisted metadata, never arbitrary exceptions/HTTP bodies.
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
