"""Run this worktree against existing Supabase accounts and records.

No migration, seed, upload or deletion is performed by this launcher.
Credentials are read from an explicitly selected env file into memory only.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

from dotenv import dotenv_values
import psutil
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
import websockets

import verify_trend_video_integration as ui

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.local/supabase-live'
STATE = OUT / 'state.json'
API_PORT, WEB_PORT, CDP_PORT = 8900, 8718, 9550
API, SITE = f'http://127.0.0.1:{API_PORT}', f'http://127.0.0.1:{WEB_PORT}'
ui.base.API, ui.base.SITE = API, SITE


def launch(command, folder, name, env=None):
    with (folder / (name + '.log')).open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
    return {'name': name, 'pid': process.pid,
            'created': psutil.Process(process.pid).create_time()}


def free_port(port):
    with socket.socket() as s:
        s.bind(('127.0.0.1', port))


def configuration(path):
    source = path.resolve()
    values = dotenv_values(source)
    required = ('DATABASE_URL', 'SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY', 'SUPABASE_STORAGE_BUCKET')
    if any(not values.get(k) for k in required):
        raise RuntimeError('Selected env file lacks required DB/Storage configuration')
    url = make_url(values['DATABASE_URL'])
    if url.get_backend_name() not in ('postgres', 'postgresql'):
        raise RuntimeError('This launcher requires PostgreSQL, not local fixtures')
    if url.drivername in ('postgres', 'postgresql'):
        url = url.set(drivername='postgresql+psycopg')
    schema = values.get('SWING_DATABASE_SCHEMA') or 'public'
    if schema != 'public':
        raise RuntimeError('Expected existing public users and records; no account copying')
    engine = create_engine(url, connect_args={'connect_timeout': 10}, hide_parameters=True)
    try:
        with engine.connect() as conn:
            conn.execute(text('SET TRANSACTION READ ONLY'))
            revision = conn.execute(text('SELECT version_num FROM public.alembic_version')).scalars().all()
            columns = set(conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='swings'")).scalars())
            if revision != ['0004'] or not {'video_delete_requested_at', 'video_deleted_at'} <= columns:
                raise RuntimeError('Approved remote migration 0004 must be applied first; this launcher never applies it')
    finally:
        engine.dispose()
    env = dict(os.environ)
    env.update({k: str(v) for k, v in values.items() if v is not None})
    env.update(SWING_DATABASE_SCHEMA='public', SWING_STORAGE_BACKEND='supabase',
               SWING_MOCK='0', SWING_LOCAL_STORAGE_ROOT='',
               SWING_CORS_ORIGINS=SITE, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
               RUN_SUPABASE_INTEGRATION_TESTS='0')
    # Use a new worker identity for this session; startup recovery cannot claim
    # an older service's pending jobs. Do not start an inference job here.
    env['SWING_WORKER_ID'] = 'trend-delete-live-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    defaults = {
        'SWING_TEMPLATE_PATH': 'modules/dtw_reference_template/reference_templates.npz',
        'SWING_YOLO_WEIGHTS': 'weights/custom_yolo_model5.pt',
        'SWING_POSE_MODEL': 'models/pose_landmarker.task',
    }
    for key, relative in defaults.items():
        value = Path(values.get(key) or relative)
        if not value.is_absolute():
            value = source.parent / value
        if not value.is_file():
            raise RuntimeError('Missing existing model/template file for ' + key)
        env[key] = str(value.resolve())
    return env


def page():
    pages = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP_PORT}/json', timeout=2))
    return next(p['webSocketDebuggerUrl'] for p in pages if p['type'] == 'page')


async def show_login(credentials=None, verify_trend=False):
    async with websockets.connect(page(), max_size=64_000_000) as ws:
        browser = ui.Browser(ws)
        try:
            for domain in ['Page', 'Runtime', 'Network']:
                await browser.call(domain + '.enable')
            await browser.call('Page.bringToFront')
            await browser.call('Emulation.setFocusEmulationEnabled', {'enabled': True})
            # A fresh document prevents old Flutter form input from surviving
            # navigation to the same hash. Never inject tokens or Session state.
            await browser.call('Page.navigate', {'url': 'about:blank'})
            await asyncio.sleep(.2)
            await browser.call('Page.navigate', {'url': SITE + '/#/login'})
            await browser.wait_text('당신의 스윙을 분석하세요')
            if credentials is None:
                return
            account = json.loads(ui.protected_password(credentials.read_bytes(), True))
            for kind, value in [('text', account['user']), ('password', account['password'])]:
                selector = '[...document.querySelectorAll("input")].find(e=>e.type===' + json.dumps(kind) + ')'
                position = await browser.js('(()=>{const e=' + selector + ';const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()')
                await browser.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', **position})
                await browser.mouse(**position)
                await asyncio.sleep(.2)
                await browser.call('Input.insertText', {'text': value})
                await asyncio.sleep(.2)
            await browser.tap('로그인')
            await browser.wait_text('스윙 추이')
            if not any(r['method'] == 'POST' and r['path'] == '/api/login' and r['status'] == 200 for r in ui.REPORT['api_responses']):
                raise RuntimeError('A normal successful login response was not observed')
            if verify_trend:
                await browser.tap('스윙 추이')
                await browser.wait_text('나의 스윙 점수 변화')
                await browser.tap('전체')
                await browser.wait_text('선택한 기록')
                await asyncio.sleep(.4)
                shots = OUT / 'screenshots'; shots.mkdir(exist_ok=True)
                ui.base.SHOTS = shots
                await browser.shot('supabase-trend-all')
            # Store only status/path evidence; exclude signed URLs and tokens.
            allowed = [r for r in ui.REPORT['api_responses']
                       if r['path'].startswith(('/api/login', '/api/users/'))]
            report = {'frontend': SITE, 'backend': API, 'user': account['user'],
                      'normal_login': True, 'trend_opened': verify_trend,
                      'api_responses': allowed, 'runtime_errors_count': len(ui.REPORT['runtime_errors']),
                      'remote_deletes_performed_by_tool': 0}
            (OUT / 'browser-read-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        finally:
            browser.reader.cancel()
            await asyncio.gather(browser.reader, return_exceptions=True)


def open_browser(state):
    chrome = next((p for p in state['processes'] if p['name'] == 'chrome'), None)
    if chrome and ui.alive(chrome):
        return
    free_port(CDP_PORT)
    folder = Path(state['folder'])
    command = ['C:/Program Files/Google/Chrome/Application/chrome.exe',
               f'--remote-debugging-port={CDP_PORT}', '--remote-debugging-address=127.0.0.1',
               '--user-data-dir=' + str(folder / 'chrome'), '--no-first-run',
               '--no-default-browser-check', '--window-size=1200,1000', 'about:blank']
    item = launch(command, folder, 'chrome')
    state['processes'] = [p for p in state['processes'] if p['name'] != 'chrome'] + [item]
    STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')
    for _ in range(100):
        try:
            page(); return
        except (OSError, StopIteration):
            if not ui.alive(item):
                raise RuntimeError('Chrome exited; inspect its private log')
            time.sleep(.2)
    raise TimeoutError('Chrome did not open')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'open', 'stop'])
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--credentials', type=Path, help='Optional current-user DPAPI JSON; never plaintext')
    parser.add_argument('--verify-trend', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.action in ('open', 'stop'):
        state = json.loads(STATE.read_text(encoding='utf-8'))
        if args.action == 'stop':
            ui.stop(state)
            print('Only owned Supabase-review helpers stopped; remote data untouched.')
            return
        if not all(ui.alive(p) for p in state['processes'] if p['name'] != 'chrome'):
            raise RuntimeError('Review servers are not running')
        open_browser(state)
        asyncio.run(show_login(args.credentials, args.verify_trend))
        print('Supabase review app opened: ' + SITE)
        return
    if args.env_file is None:
        parser.error('start requires --env-file')
    if STATE.exists() and any(ui.alive(p) for p in json.loads(STATE.read_text(encoding='utf-8'))['processes']):
        raise RuntimeError('Existing review helpers found; use open or stop')
    if not (OUT / 'web/index.html').is_file():
        raise RuntimeError('Build web for API_BASE_URL=http://127.0.0.1:8900 into .local/supabase-live/web first')
    env = configuration(args.env_file)
    for port in (API_PORT, WEB_PORT, CDP_PORT):
        free_port(port)
    folder = OUT / ('run-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'))
    folder.mkdir(exist_ok=False)
    state = {'site': SITE, 'api': API, 'folder': str(folder), 'processes': []}
    try:
        state['processes'].append(launch([sys.executable, '-X', 'utf8', '-B', '-m', 'uvicorn',
            'api.main:app', '--host', '127.0.0.1', '--port', str(API_PORT), '--no-access-log'], folder, 'api', env))
        state['processes'].append(launch([sys.executable, '-X', 'utf8', '-B', '-m', 'http.server',
            str(WEB_PORT), '--bind', '127.0.0.1', '--directory', str(OUT / 'web')], folder, 'web'))
        STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')
        for _ in range(150):
            try:
                health = json.load(urllib.request.urlopen(API + '/api/health', timeout=1))
                if health.get('mock') is not False:
                    raise RuntimeError('Mock mode must be disabled')
                break
            except OSError:
                if not all(ui.alive(p) for p in state['processes']):
                    raise RuntimeError('Review server exited; inspect private logs')
                time.sleep(.2)
        else:
            raise TimeoutError('Review API did not start')
        open_browser(state)
        asyncio.run(show_login(args.credentials, args.verify_trend))
        print('Actual Supabase/public review app running: ' + SITE + '; API: ' + API)
    except Exception:
        ui.stop(state)
        raise


if __name__ == '__main__':
    main()
