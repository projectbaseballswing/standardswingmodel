"""Combined UI check using real local API, isolated SQLite and private files.

Build web with API_BASE_URL=http://127.0.0.1:8899 first. --keep leaves the
verified app open; --open logs in again, --stop stops only this script's helpers.
Uses existing Python dependencies. No Supabase, inference or real user data.
"""
import argparse
import asyncio
import copy
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import httpx
import psutil
import websockets

import verify_original_video_delete_browser as base

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.local/integration'
API = 'http://127.0.0.1:8899'
CDP = 9549
OWNER = 'integration-review'
OTHER = 'integration-other'
ID, OTHER_ID = 'd' * 32, 'e' * 32
STATE = OUT / 'dev-state.json'
base.OUT, base.API, base.CDP = OUT, API, CDP
base.SHOTS = ROOT / 'docs/screenshots/trend-video-integration'
REPORT, check = base.REPORT, base.check


class Browser(base.Browser):
    async def tap(self, label, contains=False):
        for attempt in range(15):
            try:
                return await super().tap(label, contains)
            except AssertionError:
                if attempt == 14:
                    raise
                await asyncio.sleep(.2)

    async def login(self, user, password):
        await self.call('Page.bringToFront')
        await self.call('Emulation.setFocusEmulationEnabled', {'enabled': True})
        await super().login(user, password)

    async def fill(self, label, value):
        await super().fill(label, value)
        selector = "[...document.querySelectorAll('input,textarea')].find(e=>(e.getAttribute('aria-label')||e.getAttribute('placeholder')||'').includes(" + json.dumps(label) + "))"
        length = await self.js(f'({selector})?.value.length')
        if length != len(value):
            # Flutter can replace its editing element after the first pointer
            # event. Refocus the current element, then use real CDP text input.
            await self.js(f'({selector})?.focus()')
            await self.call('Input.insertText', {'text': value})
            await asyncio.sleep(.2)
        if await self.js(f'({selector})?.value.length') != len(value):
            raise AssertionError('Chrome did not accept text in ' + label)


def protected_password(data, decrypt=False):
    """Windows DPAPI, current Windows user only; never print a password."""
    class Blob(ctypes.Structure):
        _fields_ = [('length', ctypes.c_uint32), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, destination = Blob(len(data), buffer), Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(destination.data, destination.length)
    finally:
        kernel.LocalFree(destination.data)


def prepare(folder, password):
    os.environ.update(
        DATABASE_URL='sqlite:///' + str(folder / 'fixture.db'),
        SWING_DATABASE_SCHEMA='public', SWING_MOCK='1',
        SWING_WORKER_ID='integration-ui-check', SWING_STORAGE_BACKEND='local',
        SWING_LOCAL_STORAGE_ROOT=str(folder / 'private'), SUPABASE_URL='',
        SUPABASE_SERVICE_ROLE_KEY='', SUPABASE_STORAGE_BUCKET='', OPENAI_API_KEY='',
        RUN_SUPABASE_INTEGRATION_TESTS='0', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
    )
    sys.path.insert(0, str(ROOT))
    from api.database import engine, SessionLocal, User, Swing, Pose3D
    from api.security import hash_password
    from api.storage import LocalPrivateStorage
    from tests.video_fixture import VIDEO_BYTES
    from alembic import command
    from alembic.config import Config
    if engine.url.get_backend_name() != 'sqlite' or not Path(engine.url.database).resolve().is_relative_to(OUT.resolve()):
        raise RuntimeError('Only an isolated SQLite DB under .local/integration is allowed')
    command.upgrade(Config(str(ROOT / 'alembic.ini')), 'head')
    storage = LocalPrivateStorage(folder / 'private')
    original = folder / 'synthetic-container.mp4'
    original.write_bytes(VIDEO_BYTES)  # Storage fixture, NOT a playable swing video.
    fixture = json.loads((ROOT / 'frontend/test/fixtures/analysis_v2.json').read_text(encoding='utf-8'))['result']
    clip = json.loads((ROOT / 'frontend/test/fixtures/synthetic_left60.json').read_text(encoding='utf-8'))
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    with SessionLocal.begin() as db:
        for name in [OWNER, OTHER]:
            db.add(User(user_id=name, email=name + '@example.invalid', nickname=name,
                        password_hash=hash_password(password)))
        db.flush()
        records = [(ID, OWNER, 0, 82.4), (OTHER_ID, OTHER, 0, 99.0)]
        records += [(f'integration-{i}', OWNER, days, score)
                    for i, (days, score) in enumerate([(2, 77), (6, 74), (15, 69), (45, 61)])]
        for identifier, owner, days, score in records:
            path = f'swings/{identifier}/original.mp4'
            storage.upload(path, str(original), 'video/mp4')
            result = copy.deepcopy(fixture)
            result['overall']['score'] = score
            result['overall']['summary'] = '통합 검증용 합성 기록입니다. 실제 AI 분석 결과가 아닙니다.'
            date = now - timedelta(days=days)
            db.add(Swing(analysis_id=identifier, user_id=owner, status='done',
                         worker_id='fixture-only', recorded_at=date, created_at=date,
                         video_storage_path=path, storage_bucket=storage.bucket,
                         video_size_bytes=original.stat().st_size, content_type='video/mp4',
                         input={'type': 'video', 'handedness': 'left'}, result=result))
            db.flush()
            data = copy.deepcopy(clip)
            data.update(id=identifier, analysis_id=identifier, title='통합 검증용 합성 3D 좌표')
            data['orientation_data']['id'] = identifier
            data['orientation_data']['binding']['clip_id'] = identifier
            data['final_display_data']['binding']['clip_id'] = identifier
            raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            compressed = gzip.compress(raw, mtime=0)
            source = folder / ('pose-' + identifier + '.gz')
            source.write_bytes(compressed)
            pose_path = f'pose3d/fixture/{identifier}/display-v1.json.gz'
            storage.upload(pose_path, str(source), 'application/gzip')
            db.add(Pose3D(analysis_id=identifier, user_id=owner, status='ready',
                          storage_path=pose_path, storage_bucket=storage.bucket,
                          raw_size_bytes=len(raw), compressed_size_bytes=len(compressed),
                          payload_sha256=hashlib.sha256(raw).hexdigest(), warnings=[],
                          frame_count=data['frame_count'], handedness='left',
                          timestamps_s=data['timestamps_s'], coordinate_convention=data['coordinate_convention']))
    engine.dispose()
    (folder / 'login.dpapi').write_bytes(protected_password(password.encode()))
    return storage.root / f'swings/{ID}/original.mp4'


async def text(b):
    return await b.js("document.body.innerText+'\\n'+[...document.querySelectorAll('[aria-label]')].map(e=>e.getAttribute('aria-label')).join('\\n')")


async def browse(url, password, path, client):
    async with websockets.connect(url, max_size=64_000_000) as ws:
        b = Browser(ws)
        try:
            for domain in ['Runtime', 'Page', 'Network']:
                await b.call(domain + '.enable')
            await b.call('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 1, 'mobile': False})
            await b.login(OWNER, password)
            check('actual Flutter login and own calendar', True)

            async def trend(stage):
                await b.tap('스윙 추이')
                await b.wait_text('나의 스윙 점수 변화')
                await b.wait_text('기간 내 기록 4건')
                await b.wait_text('82.4점')
                check(stage + ': month four points and deleted target score82.4', True)
                await b.tap('최근 1주'); await b.wait_text('기간 내 기록 3건')
                await b.tap('전체'); await b.wait_text('기간 내 기록 5건')
                check(stage + ': week3 and all5', True)
                await b.shot(stage + '-trend')
                await b.tap('스윙 기록으로', True)
                await b.wait_text('스윙 기록 더보기')

            await trend('01-before-delete')
            await b.call('Input.dispatchMouseEvent', {'type': 'mouseWheel', 'x': 210, 'y': 650, 'deltaY': 500, 'deltaX': 0})
            await asyncio.sleep(.5)

            async def confirm():
                await b.tap('스윙 기록 더보기')
                await b.tap('원본 영상 삭제', True)
                await b.wait_text('복구할 수 없지만')

            await confirm(); await b.shot('02-confirmation'); await b.tap('취소')
            check('cancel sends no DELETE', path.exists() and not any(r['method'] == 'DELETE' for r in REPORT['api_responses']))
            with base.deny_file_delete(path):
                await confirm(); await b.tap('삭제')
                await b.wait_text('원본 영상 삭제를 완료하지 못했습니다')
                check('real file lock yields Storage502', any(r['method'] == 'DELETE' and r['status'] == 502 for r in REPORT['api_responses']))
                await b.shot('03-storage-failure')
            check('failed deletion preserves original', path.exists())
            check('pending deletion blocks URL409', client.get(f'/api/analyses/{ID}/video').status_code == 409)
            await asyncio.sleep(4.5)
            await confirm(); await b.tap('삭제'); await b.wait_text('원본 삭제됨')
            check('successful retry actually removes local object', not path.exists())
            check('exactly one failure and one success', [r['status'] for r in REPORT['api_responses'] if r['method'] == 'DELETE'] == [502, 200])
            await b.shot('04-deleted-calendar')
            await trend('05-after-delete')
            await b.tap('원본 삭제됨', True)
            await b.wait_text('원본 영상이 삭제되었습니다'); await b.wait_text('3D 스윙 보기')
            await b.shot('06-feedback-preserved')
            check('feedback suppresses video URL request', not any(r['method'] == 'GET' and r['path'].split('?')[0] == f'/api/analyses/{ID}/video' for r in REPORT['api_responses']))
            await b.tap('3D 스윙 보기', True)
            await b.wait_text('프레임 0 / 99'); await b.wait_text('표시 12/12')
            await asyncio.sleep(3)
            await b.shot('07-3d-after-delete')
            await b.tap('재생', True); await asyncio.sleep(.45)
            check('3D animation advances after deletion', '프레임 0 / 99' not in await text(b))
            await b.tap('일시정지', True)
            await b.tap('다음 프레임', True); await b.tap('확대', True)
            await b.shot('08-3d-playing')
            check('3D playback pause seek and zoom controls work', True)

            # Full navigation discards the existing in-memory Session. Authenticate again.
            await b.login(OWNER, password)
            await b.wait_text('원본 삭제됨')
            await trend('09-after-relogin')
            await b.tap('원본 삭제됨', True)
            await b.wait_text('원본 영상이 삭제되었습니다')
            await b.tap('3D 스윙 보기', True); await b.wait_text('표시 12/12')
            check('fresh login retains deletion feedback and 3D', True)
            check('no Chrome runtime exceptions', not REPORT['runtime_errors'])
        except Exception:
            await b.shot('failure')
            raise
        finally:
            b.reader.cancel(); await asyncio.gather(b.reader, return_exceptions=True)


def launch(command, folder, name):
    with (folder / (name + '.log')).open('w', encoding='utf-8') as log:
        p = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    return {'pid': p.pid, 'created': psutil.Process(p.pid).create_time(), 'name': name}


def alive(item):
    try:
        return psutil.Process(item['pid']).create_time() == item['created']
    except psutil.NoSuchProcess:
        return False


def stop(state):
    for item in reversed(state['processes']):
        if alive(item):
            base.stop_owned(psutil.Process(item['pid']), item['created'])


def page():
    pages = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json', timeout=2))
    return next(p['webSocketDebuggerUrl'] for p in pages if p['type'] == 'page')


async def reopen(state):
    password = protected_password((Path(state['folder']) / 'login.dpapi').read_bytes(), True).decode()
    async with websockets.connect(page(), max_size=64_000_000) as ws:
        b = Browser(ws)
        try:
            for domain in ['Runtime', 'Page', 'Network']:
                await b.call(domain + '.enable')
            await b.login(OWNER, password)
        finally:
            b.reader.cancel(); await asyncio.gather(b.reader, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--keep', action='store_true')
    mode.add_argument('--open', action='store_true')
    mode.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.open or args.stop:
        state = json.loads(STATE.read_text(encoding='utf-8'))
        base.SITE = state['site']
        if args.stop:
            stop(state); print('Owned verification helpers stopped. DB and files preserved.')
        else:
            if not all(alive(p) for p in state['processes']):
                raise RuntimeError('Verification helpers are not running; rerun with --keep')
            asyncio.run(reopen(state)); print('Authenticated isolated fixture app opened at ' + base.SITE)
        return
    if STATE.exists() and any(alive(p) for p in json.loads(STATE.read_text(encoding='utf-8'))['processes']):
        raise RuntimeError('Existing verification helpers running. Use --open or --stop first.')
    for port in (8899, CDP):
        with socket.socket() as s:
            s.bind(('127.0.0.1', port))  # Do not attach to someone else's server.
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); webport = s.getsockname()[1]
    folder = OUT / ('browser-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'))
    folder.mkdir(exist_ok=False)
    password = secrets.token_urlsafe(24)
    path = prepare(folder, password)
    base.SITE = f'http://127.0.0.1:{webport}'
    state = {'site': base.SITE, 'api': API, 'folder': str(folder), 'user': OWNER, 'processes': []}
    success = False
    try:
        commands = [
            ('api', [sys.executable, '-X', 'utf8', '-B', '-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1', '--port', '8899', '--no-access-log']),
            ('web', [sys.executable, '-X', 'utf8', '-B', '-m', 'http.server', str(webport), '--bind', '127.0.0.1', '--directory', str(ROOT / 'frontend/build/web')]),
            ('chrome', ['C:/Program Files/Google/Chrome/Application/chrome.exe', f'--remote-debugging-port={CDP}', '--user-data-dir=' + str(folder / 'chrome'), '--no-first-run', '--no-default-browser-check', *([] if args.keep else ['--headless=new']), 'about:blank']),
        ]
        for name, command in commands:
            state['processes'].append(launch(command, folder, name))
        STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')
        for _ in range(150):
            if not all(alive(p) for p in state['processes']):
                raise RuntimeError('Verification helper exited; inspect .local/integration logs')
            try:
                urllib.request.urlopen(API + '/api/health', timeout=1).close()
                url = page(); break
            except (OSError, StopIteration):
                time.sleep(.2)
        else:
            raise TimeoutError('Local servers did not start')
        with httpx.Client(base_url=API, trust_env=False) as client:
            check('anonymous DELETE401', client.delete(f'/api/analyses/{ID}/video').status_code == 401)
            token = client.post('/api/login', json={'id': OWNER, 'password': password}).json()['access_token']
            client.headers['Authorization'] = 'Bearer ' + token
            check('other user DELETE403', client.delete(f'/api/analyses/{OTHER_ID}/video').status_code == 403)
            before = client.get(f'/api/analyses/{ID}?include_series=true').json()
            pose = client.get(f'/api/analyses/{ID}/pose-3d').json()
            rows_before = client.get(f'/api/users/{OWNER}/swings').json()['items']
            signed = client.get(f'/api/analyses/{ID}/video').json()['url']
            check('synthetic original stored and served before delete', client.get(signed).status_code == 200)
            other = path.parents[1] / OTHER_ID / 'original.mp4'
            other_hash = hashlib.sha256(other.read_bytes()).hexdigest()
            asyncio.run(browse(url, password, path, client))
            after = client.get(f'/api/analyses/{ID}?include_series=true').json()
            check('all analysis fields except video status unchanged', {k: v for k, v in before.items() if k != 'video_status'} == {k: v for k, v in after.items() if k != 'video_status'})
            check('full pose payload unchanged', client.get(f'/api/analyses/{ID}/pose-3d').json() == pose)
            check('deleted video GET410', client.get(f'/api/analyses/{ID}/video').status_code == 410)
            check('old local signed capability blocked', client.get(signed).status_code in (404, 410))
            rows_after = client.get(f'/api/users/{OWNER}/swings').json()['items']
            def scores(rows):
                return [(r['analysis_id'], r['recorded_at'], r['status'], r['score']) for r in rows]
            check('all trend IDs dates statuses scores unchanged', scores(rows_before) == scores(rows_after))
            check('other user file preserved', other.exists() and hashlib.sha256(other.read_bytes()).hexdigest() == other_hash)
            check('repeat deletion idempotent200', client.delete(f'/api/analyses/{ID}/video').json()['already_deleted'])
        REPORT.update(status='passed', site=base.SITE, api=API, kept=args.keep,
                      limitation='Synthetic scores and animated geometry; synthetic MP4 container is not playable. No inference or Supabase deletion tested.')
        success = True
    except Exception as exc:
        REPORT.update(status='failed', failure=str(exc)); raise
    finally:
        if not (success and args.keep):
            stop(state)
        (OUT / 'browser-validation.json').write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'status': REPORT.get('status'), 'checks': len(REPORT['checks']), 'site': base.SITE, 'kept': success and args.keep}))


if __name__ == '__main__':
    main()
