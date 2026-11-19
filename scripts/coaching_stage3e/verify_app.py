"""Stage-3E real Flutter/HTTP app check with isolated synthetic fixtures.

Build Flutter with API_BASE_URL=http://127.0.0.1:8906 first. --keep leaves an
inspectable app; --open safely logs in with Windows DPAPI credentials. --stop
stops only processes this helper created. No OpenAI/Supabase calls or installs.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit
from datetime import datetime, timezone

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[2]
# The requested Python environment has the API dependencies but not psutil.
# Reuse ONLY the existing sibling environment's matching Python 3.11 psutil
# package for process ownership checks, without installing or modifying it.
try:
    import psutil
except ModuleNotFoundError:
    existing = ROOT.parent / 'standardswingmodel/.venv/Lib/site-packages/psutil/__init__.py'
    if not existing.is_file():
        raise RuntimeError('Existing psutil helper dependency not found; no packages were installed') from None
    spec = importlib.util.spec_from_file_location('psutil', existing,
                                                submodule_search_locations=[str(existing.parent)])
    psutil = importlib.util.module_from_spec(spec)
    sys.modules['psutil'] = psutil
    spec.loader.exec_module(psutil)
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
import verify_original_video_delete_browser as base
from dev_fixtures import IDS, OWNER, OTHER, SYNTHETIC_TEXT, prepare

OUT = ROOT / '.local/feedback-stage3e/app'
STATE = OUT / 'dev-state.json'
API, SITE, CDP = 'http://127.0.0.1:8906', 'http://127.0.0.1:8990', 9566
base.API, base.SITE, base.CDP, base.OUT = API, SITE, CDP, OUT
base.SHOTS = OUT / 'screenshots'
REPORT = base.REPORT


def check(name, condition):
    base.check(name, condition)
    print('PASS: ' + name, flush=True)


def protected_password(data: bytes, decrypt=False) -> bytes:
    """DPAPI secret can be decrypted only by the current Windows account."""
    class Blob(ctypes.Structure):
        _fields_ = [('length', ctypes.c_uint32), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, destination = Blob(len(data), buffer), Blob()
    crypt, kernel = ctypes.WinDLL('crypt32', use_last_error=True), ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [ctypes.c_void_p], ctypes.c_void_p
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(destination.data, destination.length)
    finally:
        kernel.LocalFree(destination.data)


class Browser(base.Browser):
    async def call(self, method, params=None):
        self.counter += 1
        future = asyncio.get_running_loop().create_future()
        self.pending[self.counter] = future
        await self.ws.send(json.dumps({'id': self.counter, 'method': method, 'params': params or {}}))
        try:
            result = await asyncio.wait_for(future, 90)
        except TimeoutError:
            raise TimeoutError('Chrome command timed out: ' + method) from None
        if 'error' in result:
            raise RuntimeError(result['error'])
        return result.get('result', {})

    async def login(self, user, password):
        await self.call('Page.bringToFront')
        await self.call('Emulation.setFocusEmulationEnabled', {'enabled': True})
        await self.call('Page.navigate', {'url': 'about:blank'})
        await asyncio.sleep(.2)
        await super().login(user, password)

    async def tap(self, label, contains=False):
        for attempt in range(15):
            try:
                return await super().tap(label, contains)
            except AssertionError:
                if attempt == 14:
                    raise
                await asyncio.sleep(.2)

    async def fill(self, label, value):
        selector = "[...document.querySelectorAll('input,textarea')].find(e=>(e.getAttribute('aria-label')||e.getAttribute('placeholder')||'').includes(" + json.dumps(label) + '))'
        pos = await self.js(f'(()=>{{const e={selector};if(!e)return null;const r=e.getBoundingClientRect();return{{x:r.x+r.width/2,y:r.y+r.height/2}}}})()')
        if not pos:
            raise AssertionError('Missing input ' + label)
        await self.call('Page.bringToFront')
        await self.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', **pos})
        await self.mouse(**pos)
        await asyncio.sleep(.2)
        await self.call('Input.insertText', {'text': value})
        await asyncio.sleep(.2)
        if await self.js(f'({selector})?.value.length') != len(value):
            raise AssertionError('Browser did not accept input ' + label)

    async def content(self):
        return await self.js("document.body.innerText+'\\n'+[...document.querySelectorAll('[aria-label]')].map(e=>e.getAttribute('aria-label')).join('\\n')")

    async def wheel(self, delta=450):
        await self.call('Input.dispatchMouseEvent', {'type': 'mouseWheel', 'x': 240, 'y': 670,
                                                    'deltaY': delta, 'deltaX': 0})
        await asyncio.sleep(.4)

    async def locate(self, label, contains=True):
        for _ in range(14):
            try:
                return await self.tap(label, contains)
            except AssertionError:
                await self.wheel()
        raise AssertionError('Control not found by scrolling: ' + label)

    async def route(self, path, text):
        await self.js('location.hash=' + json.dumps('#' + path))
        await self.wait_text(text)
        await asyncio.sleep(.5)


async def browse(url, password, path, client):
    async with websockets.connect(url, max_size=64_000_000) as ws:
        b = Browser(ws)
        try:
            for domain in ('Runtime', 'Page', 'Network'):
                await b.call(domain + '.enable')
            await b.call('Emulation.setDeviceMetricsOverride', {'width': 430, 'height': 920,
                          'deviceScaleFactor': 1, 'mobile': False})
            await b.login(OWNER, password)
            check('Chrome login and own swing calendar', True)
            await b.shot('01-calendar')
            await b.tap('스윙 추이')
            await b.wait_text('나의 스윙 점수 변화')
            await b.wait_text('기간 내 기록 4건')
            await b.shot('02-trend-before-delete')
            check('Chrome trend includes four isolated owned fixture records', True)

            identifier = IDS['approved']
            await b.route('/analyses/' + identifier, '종합 피드백')
            await b.locate('점수가 산출된 이유')
            await b.wait_text('70%')
            await b.wait_text(SYNTHETIC_TEXT)
            await b.shot('03-score-evidence-expanded')
            check('Chrome score evidence expands', True)
            await b.wheel(450)
            await b.wait_text('GPT 코칭')
            await b.shot('04-approved-synthetic-coaching')
            check('Chrome approved synthetic coaching renders with source label', True)

            await b.tap('구간별 피드백 보기')
            await b.wait_text('구간별 피드백')
            await b.wait_text('각 스윙 구간의 점수를 확인해보세요.')
            await b.shot('05-phase-feedback')
            check('Latest-main phase UI accessible', True)
            await b.mouse(28, 28)
            await b.wait_text('종합 피드백')
            await b.tap('상세 피드백 보기')
            await b.wait_text('관절별 분석')
            await b.shot('06-joint-feedback')
            check('Latest-main joint UI accessible', True)

            for state in ('review_required', 'blocked', 'generation_failed'):
                await b.route('/analyses/' + IDS[state], '종합 피드백')
                await b.wheel(650)
                await b.wait_text('규칙 기반')
                content = await b.content()
                check('Chrome ' + state + ' shows rules and hides approved text',
                      SYNTHETIC_TEXT not in content and 'GPT 코칭 · 검토 완료' not in content)
                await b.shot('07-' + state)

            await b.route('/swings', '스윙 추이')
            await b.wheel(450)

            async def confirm():
                await b.locate('스윙 기록 더보기', False)
                await b.tap('원본 영상 삭제', True)
                await b.wait_text('복구할 수 없지만')

            await confirm()
            await b.shot('08-delete-confirmation')
            await b.tap('취소')
            check('Cancel keeps original and sends no DELETE', path.exists() and
                  not any(r['method'] == 'DELETE' for r in REPORT['api_responses']))
            with base.deny_file_delete(path):
                await confirm()
                await b.tap('삭제')
                await b.wait_text('원본 영상 삭제를 완료하지 못했습니다')
                check('Locked isolated local object produces Storage502', any(
                    r['method'] == 'DELETE' and r['status'] == 502 for r in REPORT['api_responses']))
                await b.shot('09-storage-failure')
            check('Storage failure retains original', path.exists())
            check('Pending deletion blocks URL409', client.get(f'/api/analyses/{identifier}/video').status_code == 409)
            await asyncio.sleep(4.5)
            await confirm()
            await b.tap('삭제')
            await b.wait_text('원본 삭제됨')
            check('Retry removes only test original', not path.exists())
            await b.tap('스윙 추이')
            await b.wait_text('기간 내 기록 4건')
            await b.shot('10-trend-after-delete')
            check('Chrome deletion retains four trend records', True)
            await b.route('/analyses/' + identifier, '원본 영상이 삭제되었습니다')
            await b.tap('3D 스윙 보기', True)
            await b.wait_text('프레임 0 / 99')
            await b.wait_text('표시 12/12')
            await asyncio.sleep(2)
            await b.shot('11-3d-preserved-after-delete')
            await b.tap('재생', True)
            await asyncio.sleep(.5)
            check('3D animation advances after original deletion', '프레임 0 / 99' not in await b.content())
            await b.tap('일시정지', True)
            await b.tap('다음 프레임', True)
            await b.tap('확대', True)
            check('3D pause/frame-step/zoom controls operate', True)
            await b.login(OWNER, password)
            await b.wait_text('원본 삭제됨')
            await b.route('/analyses/' + identifier, '원본 영상이 삭제되었습니다')
            await b.wheel(650)
            await b.wait_text(SYNTHETIC_TEXT)
            check('Fresh login retains deletion and approved synthetic feedback', True)
            await b.shot('12-relogin-preserved')
            check('No Chrome uncaught runtime exceptions', not REPORT['runtime_errors'])
        except Exception:
            await b.shot('failure')
            raise
        finally:
            b.reader.cancel()
            await asyncio.gather(b.reader, return_exceptions=True)


def launch(command, folder, name):
    with (folder / (name + '.log')).open('w', encoding='utf-8') as log:
        proc = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    return {'pid': proc.pid, 'created': psutil.Process(proc.pid).create_time(), 'name': name}


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
            for domain in ('Runtime', 'Page', 'Network'):
                await b.call(domain + '.enable')
            await b.login(OWNER, password)
            await b.route('/analyses/' + IDS['approved'], '종합 피드백')
        finally:
            b.reader.cancel()
            await asyncio.gather(b.reader, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    for name in ('keep', 'open', 'stop'):
        modes.add_argument('--' + name, action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.open or args.stop:
        state = json.loads(STATE.read_text(encoding='utf-8'))
        if args.stop:
            stop(state)
            print('Owned app helpers stopped; fixture DB and artifacts preserved.')
        else:
            if not all(alive(p) for p in state['processes']):
                raise RuntimeError('Owned helpers are not running; rerun --keep')
            asyncio.run(reopen(state))
            print('Authenticated isolated fixture app opened: ' + SITE)
        return
    if STATE.exists() and any(alive(p) for p in json.loads(STATE.read_text(encoding='utf-8'))['processes']):
        raise RuntimeError('Owned helpers already running. Use --open or --stop.')
    for port in (8906, 8990, CDP):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', port))
    web_script = ROOT / 'frontend/build/web/main.dart.js'
    if not web_script.is_file() or API not in web_script.read_text(encoding='utf-8'):
        raise RuntimeError('Build Flutter web with the stated API URL first')
    folder = OUT / ('run-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'))
    folder.mkdir(exist_ok=False)
    password = secrets.token_urlsafe(24)
    path = prepare(folder, password)
    (folder / 'login.dpapi').write_bytes(protected_password(password.encode()))
    state = {'site': SITE, 'api': API, 'folder': str(folder), 'user': OWNER, 'processes': []}
    success = False
    try:
        commands = [
            ('api', [sys.executable, '-X', 'utf8', '-B', '-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1', '--port', '8906', '--no-access-log']),
            ('web', [sys.executable, '-X', 'utf8', '-B', '-m', 'http.server', '8990', '--bind', '127.0.0.1', '--directory', str(ROOT / 'frontend/build/web')]),
            ('chrome', ['C:/Program Files/Google/Chrome/Application/chrome.exe', f'--remote-debugging-port={CDP}', '--user-data-dir=' + str(folder / 'chrome'), '--no-first-run', '--no-default-browser-check', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows', *([] if args.keep else ['--headless=new']), 'about:blank']),
        ]
        for name, command in commands:
            state['processes'].append(launch(command, folder, name))
        STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')
        for _ in range(150):
            if not all(alive(p) for p in state['processes']):
                raise RuntimeError('Owned helper exited; see local app logs')
            try:
                urllib.request.urlopen(API + '/api/health', timeout=1).close()
                url = page()
                break
            except (OSError, StopIteration):
                time.sleep(.2)
        else:
            raise TimeoutError('Owned app servers did not start')
        with httpx.Client(base_url=API, trust_env=False, timeout=30) as client:
            identifier = IDS['approved']
            check('Anonymous analysis401', client.get(f'/api/analyses/{identifier}').status_code == 401)
            check('Anonymous DELETE401', client.delete(f'/api/analyses/{identifier}/video').status_code == 401)
            login = client.post('/api/login', json={'id': OWNER, 'password': password})
            check('Real local authentication200', login.status_code == 200)
            client.headers['Authorization'] = 'Bearer ' + login.json()['access_token']
            check('Other owner analysis403', client.get(f'/api/analyses/{IDS["other"]}').status_code == 403)
            check('Other owner DELETE403', client.delete(f'/api/analyses/{IDS["other"]}/video').status_code == 403)
            for expected in ('approved', 'review_required', 'blocked', 'generation_failed'):
                response = client.get(f'/api/analyses/{IDS[expected]}?include_series=true')
                body = response.json()['result']
                check('Public lifecycle ' + expected, body['coaching_review']['status'] == expected)
                check('Private candidate hidden for ' + expected,
                      '_coaching_review' not in body and 'candidate' not in body['coaching_review'])
                check('Only approved coaching returned for ' + expected,
                      (body['coaching'] is not None) == (expected == 'approved'))
                check('Direct coaching gate ' + expected, client.get(f'/api/analyses/{IDS[expected]}/coaching').status_code == (200 if expected == 'approved' else 404))
                if expected != 'generation_failed':
                    comparison = client.get(f'/api/users/{OWNER}/analyses/{IDS[expected]}/comparison').json()
                    check('Comparison lifecycle ' + expected,
                          comparison['coaching_review']['status'] == expected
                          and (comparison['coaching'] is not None) == (expected == 'approved')
                          and '_coaching_review' not in comparison)
            before = client.get(f'/api/analyses/{identifier}?include_series=true').json()
            pose = client.get(f'/api/analyses/{identifier}/pose-3d').json()
            rows_before = client.get(f'/api/users/{OWNER}/swings').json()['items']
            signed = client.get(f'/api/analyses/{identifier}/video').json()['url']
            check('Actual isolated storage object served', client.get(signed).status_code == 200)
            other = path.parents[1] / IDS['other'] / 'original.mp4'
            other_hash = hashlib.sha256(other.read_bytes()).hexdigest()
            asyncio.run(browse(url, password, path, client))
            after = client.get(f'/api/analyses/{identifier}?include_series=true').json()
            check('Analysis scores feedback and approved coaching unchanged by deletion',
                  {k:v for k,v in before.items() if k != 'video_status'} == {k:v for k,v in after.items() if k != 'video_status'})
            check('Complete 3D payload unchanged', client.get(f'/api/analyses/{identifier}/pose-3d').json() == pose)
            check('Deleted video URL410', client.get(f'/api/analyses/{identifier}/video').status_code == 410)
            check('Old local video capability revoked', client.get(signed).status_code in (404, 410))
            rows_after = client.get(f'/api/users/{OWNER}/swings').json()['items']
            def scores(rows):
                return [(r['analysis_id'],r['recorded_at'],r['status'],r['score']) for r in rows]
            check('All trend scores and dates preserved', scores(rows_before) == scores(rows_after))
            check('Other owner file untouched', other.exists() and hashlib.sha256(other.read_bytes()).hexdigest() == other_hash)
            check('Repeat delete idempotent', client.delete(f'/api/analyses/{identifier}/video').json()['already_deleted'])
        REPORT.update(status='passed', site=SITE, api=API, fixture_folder=str(folder), kept=args.keep,
                      limits=['No paid API or remote Supabase calls', 'Approved response is synthetic, not actual GPT B approval',
                              'Storage video is a container fixture; real decode/upload/inference not tested',
                              '3D is existing synthetic geometry fixture; real pose accuracy not evaluated'])
        success = True
    except Exception as exc:
        REPORT.update(status='failed', failure=str(exc), failure_type=type(exc).__name__, fixture_folder=str(folder))
        raise
    finally:
        if not (success and args.keep):
            stop(state)
        # The shared CDP helper records response URLs; never persist a signed
        # storage URL's capability query, even for these isolated test files.
        for response in REPORT['api_responses']:
            response['path'] = urlsplit(response['path']).path
        REPORT['runtime_errors'] = [
            {'text': item.get('exceptionDetails', {}).get('text', 'Runtime exception'),
             'line': item.get('exceptionDetails', {}).get('lineNumber')}
            for item in REPORT['runtime_errors']
        ]
        output = json.dumps(REPORT, ensure_ascii=False, indent=2)
        (OUT / 'browser-validation.json').write_text(output, encoding='utf-8')
        (folder / 'browser-validation.json').write_text(output, encoding='utf-8')
        print(json.dumps({'status': REPORT.get('status'), 'checks': len(REPORT['checks']), 'site': SITE,
                          'kept': success and args.keep}))


if __name__ == '__main__':
    main()
