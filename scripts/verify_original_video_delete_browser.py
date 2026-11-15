"""Isolated Chrome verification. No remote DB/Storage and no inference.

Build Flutter with API_BASE_URL=http://127.0.0.1:8898, then run this script
using the existing API development Python. Fixtures are not real swing results.
"""
import asyncio,base64,copy,ctypes,gzip,hashlib,json,os,secrets,subprocess,sys,threading,time,urllib.request
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import httpx,psutil,websockets

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.local/video-delete';WEB=ROOT/'frontend/build/web';API='http://127.0.0.1:8898';SITE='';CDP=9548
SHOTS=ROOT/'docs/screenshots/original-video-delete'
REPORT={'fixture_only':True,'storage':'Actual temporary LocalPrivateStorage files; Supabase not contacted','checks':[],'api_responses':[],'runtime_errors':[]}
ID='d'*32;OTHER_ID='e'*32

def check(name,condition):
    REPORT['checks'].append({'name':name,'passed':bool(condition)})
    if not condition:raise AssertionError(name)

class Browser:
    def __init__(self,ws):
        self.ws=ws;self.counter=0;self.pending={};self.methods={};self.reader=asyncio.create_task(self.receive())
    async def receive(self):
        async for raw in self.ws:
            m=json.loads(raw)
            if 'id' in m:
                f=self.pending.pop(m['id'],None)
                if f and not f.done():f.set_result(m)
            elif m.get('method')=='Network.requestWillBeSent':self.methods[m['params']['requestId']]=m['params']['request']['method']
            elif m.get('method')=='Runtime.exceptionThrown':REPORT['runtime_errors'].append(m['params'])
            elif m.get('method')=='Network.responseReceived':
                r=m['params']['response']
                if r['url'].startswith(API):REPORT['api_responses'].append({'path':r['url'].removeprefix(API),'status':r['status'],'method':self.methods.get(m['params']['requestId'])})
    async def call(self,method,params=None):
        self.counter+=1;f=asyncio.get_running_loop().create_future();self.pending[self.counter]=f
        await self.ws.send(json.dumps({'id':self.counter,'method':method,'params':params or {}}));r=await asyncio.wait_for(f,40)
        if 'error' in r:raise RuntimeError(r['error'])
        return r.get('result',{})
    async def js(self,code):
        r=await self.call('Runtime.evaluate',{'expression':code,'returnByValue':True,'awaitPromise':True})
        if 'exceptionDetails' in r:raise RuntimeError(r['exceptionDetails'])
        return r['result'].get('value')
    async def wait_text(self,text):
        for _ in range(200):
            await self.js("document.querySelector('flt-semantics-placeholder')?.click()")
            content=await self.js("document.body.innerText+'\\n'+[...document.querySelectorAll('[aria-label]')].map(e=>e.getAttribute('aria-label')).join('\\n')")
            if text in content:await asyncio.sleep(.35);return
            await asyncio.sleep(.15)
        raise AssertionError('Missing UI text: '+text)
    async def mouse(self,x,y):
        for kind in ['mousePressed','mouseReleased']:await self.call('Input.dispatchMouseEvent',{'type':kind,'x':x,'y':y,'button':'left','clickCount':1})
    async def tap(self,label,contains=False):
        result=await self.js("""(()=>{const label=LABEL;const es=[...document.querySelectorAll('flt-semantics, [aria-label]')].filter(e=>{const t=((e.innerText||'')+' '+(e.getAttribute('aria-label')||'')).replace(/\\s+/g,' ').trim();const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&r.top>=0&&r.bottom<=innerHeight&&(PART?t.includes(label):(t===label||t.startsWith(label+' Tab ')))});es.sort((a,b)=>a.getBoundingClientRect().width*a.getBoundingClientRect().height-b.getBoundingClientRect().width*b.getBoundingClientRect().height);const e=es[0];if(!e)return null;const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()""".replace('LABEL',json.dumps(label)).replace('PART',str(contains).lower()))
        if result is None:raise AssertionError('Missing visible control: '+label)
        await self.mouse(**result);await asyncio.sleep(.4)
    async def fill(self,label,value):
        selector="[...document.querySelectorAll('input,textarea')].find(e=>(e.getAttribute('aria-label')||e.getAttribute('placeholder')||'').includes("+json.dumps(label)+"))"
        p=await self.js(f'(()=>{{const e={selector};if(!e)return null;const r=e.getBoundingClientRect();e.focus();return{{x:r.x+r.width/2,y:r.y+r.height/2}}}})()')
        if not p:raise AssertionError('Missing input '+label)
        await self.mouse(**p);await self.call('Input.insertText',{'text':value});await asyncio.sleep(.2)
    async def login(self,user,password):
        await self.call('Page.navigate',{'url':SITE+'/#/login'});await self.wait_text('당신의 스윙을 분석하세요')
        await self.fill('아이디',user);await self.fill('비밀번호',password);await self.tap('로그인');await self.wait_text('스윙 추이')
    async def shot(self,name):
        r=await self.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False});SHOTS.mkdir(parents=True,exist_ok=True);(SHOTS/(name+'.png')).write_bytes(base64.b64decode(r['data']))


def prepare(folder, password):
    os.environ.update(DATABASE_URL='sqlite:///'+str(folder/'fixture.db'), SWING_DATABASE_SCHEMA='public',
                      SWING_MOCK='1', SWING_WORKER_ID='delete-ui-check', SWING_STORAGE_BACKEND='local',
                      SWING_LOCAL_STORAGE_ROOT=str(folder/'private'), SUPABASE_URL='', SUPABASE_SERVICE_ROLE_KEY='',
                      SUPABASE_STORAGE_BUCKET='', OPENAI_API_KEY='', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    sys.path.insert(0,str(ROOT))
    from api.database import engine,SessionLocal,User,Swing,Pose3D
    if engine.url.get_backend_name()!='sqlite' or not Path(engine.url.database).resolve().is_relative_to(OUT.resolve()):
        raise RuntimeError('Verification requires its isolated SQLite database')
    from alembic import command
    from alembic.config import Config
    command.upgrade(Config(str(ROOT/'alembic.ini')),'head')
    from api.storage import LocalPrivateStorage
    from api.security import hash_password
    from tests.video_fixture import VIDEO_BYTES
    storage=LocalPrivateStorage(folder/'private')
    source=folder/'fixture-original.mp4';source.write_bytes(VIDEO_BYTES)
    # Synthetic container bytes exercise storage, not video decoding or AI.
    result=json.loads((ROOT/'frontend/test/fixtures/analysis_v2.json').read_text(encoding='utf-8'))['result']
    now=datetime.now(timezone.utc)
    with SessionLocal.begin() as db:
        for name in ['video-delete-ui','video-delete-other']:
            db.add(User(user_id=name,email=name+'@example.invalid',nickname=name,password_hash=hash_password(password)))
        db.flush()
        for identifier,owner in [(ID,'video-delete-ui'),(OTHER_ID,'video-delete-other')]:
            path=f'swings/{identifier}/original.mp4';storage.upload(path,str(source),'video/mp4')
            db.add(Swing(analysis_id=identifier,user_id=owner,status='done',worker_id='fixture-only',recorded_at=now,
                         video_storage_path=path,storage_bucket=storage.bucket,video_size_bytes=source.stat().st_size,
                         content_type='video/mp4',input={'type':'video','handedness':'right'},result=copy.deepcopy(result)))
            db.flush()
            raw=json.dumps({'id':identifier,'analysis_id':identifier,'data_kind':'analysis','frames':[]}).encode()
            compressed=gzip.compress(raw);pose_source=folder/'fixture-pose.gz';pose_source.write_bytes(compressed)
            pose_path=f'pose3d/fixture/{identifier}/display-v1.json.gz';storage.upload(pose_path,str(pose_source),'application/gzip')
            db.add(Pose3D(analysis_id=identifier,user_id=owner,status='ready',storage_path=pose_path,storage_bucket=storage.bucket,
                          raw_size_bytes=len(raw),compressed_size_bytes=len(compressed),payload_sha256=hashlib.sha256(raw).hexdigest(),warnings=[]))
    engine.dispose()
    return storage.root/f'swings/{ID}/original.mp4'


@contextmanager
def deny_file_delete(path):
    """Windows handle sharing failure on this newly created test file only."""
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
    kernel.CreateFileW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.CreateFileW(str(path),0x80000000,0,None,3,0,None)
    if handle in (None,ctypes.c_void_p(-1).value):raise ctypes.WinError(ctypes.get_last_error())
    try:yield
    finally:kernel.CloseHandle(handle)


async def browse(socket_url,password,path,client):
    async with websockets.connect(socket_url,max_size=64_000_000) as ws:
        b=Browser(ws)
        try:
            for d in ['Runtime','Page','Network']:await b.call(d+'.enable')
            await b.call('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':False})
            await b.login('video-delete-ui',password)
            await b.call('Input.dispatchMouseEvent',{'type':'mouseWheel','x':210,'y':650,'deltaY':500,'deltaX':0});await asyncio.sleep(.5)
            await b.shot('01-list-before-fixture')
            async def confirm():
                await b.tap('스윙 기록 더보기');await b.tap('원본 영상 삭제',True);await b.wait_text('복구할 수 없지만')
            await confirm();await b.shot('02-delete-confirmation-fixture');await b.tap('취소')
            check('cancel makes no DELETE and preserves file',path.exists() and not any(r['method']=='DELETE' for r in REPORT['api_responses']))
            with deny_file_delete(path):
                await confirm();await b.tap('삭제');await b.wait_text('원본 영상 삭제를 완료하지 못했습니다')
                check('real filesystem failure returns502',any(r['method']=='DELETE' and r['status']==502 for r in REPORT['api_responses']))
                await b.shot('03-delete-error-fixture')
            check('failure retains original',path.exists())
            check('pending intent blocks signed URL',client.get(f'/api/analyses/{ID}/video').status_code==409)
            await asyncio.sleep(4.5)  # Let the failure snackbar leave the button area.
            await confirm();await b.tap('삭제');await b.wait_text('원본 삭제됨')
            check('confirmed retry removes actual file',not path.exists())
            check('one failed and one successful UI DELETE',[(r['status']) for r in REPORT['api_responses'] if r['method']=='DELETE']==[502,200])
            await b.shot('04-list-deleted-fixture')
            await b.tap('원본 삭제됨',True);await b.wait_text('원본 영상이 삭제되었습니다');await b.wait_text('3D 스윙 보기')
            check('feedback keeps 3D entry and deleted notice',True);await b.shot('05-feedback-deleted-fixture')
            calls=[r for r in REPORT['api_responses'] if r['method']=='GET' and r['path'].split('?')[0]==f'/api/analyses/{ID}/video']
            check('deleted feedback does not request video URL',not calls)
            await b.mouse(28,28);await b.wait_text('원본 삭제됨');check('return keeps analysis record',True)
            check('no Chrome runtime exceptions',not REPORT['runtime_errors'])
        except Exception:
            r=await b.call('Page.captureScreenshot',{'format':'png'});(OUT/'browser-failure.png').write_bytes(base64.b64decode(r['data']))
            raise
        finally:
            b.reader.cancel();await asyncio.gather(b.reader,return_exceptions=True)


def stop_owned(proc,created):
    try:
        parent=psutil.Process(proc.pid)
        if parent.create_time()!=created:return
        processes=parent.children(recursive=True)+[parent]
        for p in processes:
            try:p.terminate()
            except psutil.Error:pass
        _,remaining=psutil.wait_procs(processes,timeout=8)
        if remaining:
            for p in remaining:
                try:p.kill()
                except psutil.Error:pass
            _,remaining=psutil.wait_procs(remaining,timeout=5)
            if remaining:REPORT.setdefault('cleanup_pending',[]).extend(p.pid for p in remaining)
    except psutil.NoSuchProcess:pass


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass


def main():
    global SITE
    folder=OUT/('browser-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'));folder.mkdir(parents=True,exist_ok=False)
    password=secrets.token_urlsafe(18);path=prepare(folder,password)
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(WEB)))
    SITE=f'http://127.0.0.1:{server.server_port}'
    threading.Thread(target=server.serve_forever,daemon=True).start();owned=[]
    try:
        for cmd,name in [([sys.executable,'-X','utf8','-B','-m','uvicorn','api.main:app','--host','127.0.0.1','--port','8898','--no-access-log'],'api'),
                         (['C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new',f'--remote-debugging-port={CDP}','--user-data-dir='+str(folder/'chrome'),'--no-first-run','--no-default-browser-check','about:blank'],'chrome')]:
            with (folder/(name+'.log')).open('w',encoding='utf-8') as log:
                proc=subprocess.Popen(cmd,cwd=ROOT,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            owned.append((proc,psutil.Process(proc.pid).create_time()))
        for _ in range(150):
            if any(p.poll() is not None for p,_ in owned):raise RuntimeError('Owned child exited; see .local logs')
            try:
                with urllib.request.urlopen(API+'/api/health',timeout=1) as r:assert r.status==200
                pages=json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json',timeout=1))
                socket_url=next(p['webSocketDebuggerUrl'] for p in pages if p['type']=='page');break
            except (OSError,StopIteration):time.sleep(.2)
        else:raise TimeoutError('Local servers did not start')
        with httpx.Client(base_url=API,trust_env=False) as client:
            check('unauthenticated DELETE401',client.delete(f'/api/analyses/{ID}/video').status_code==401)
            token=client.post('/api/login',json={'id':'video-delete-ui','password':password}).json()['access_token']
            client.headers['Authorization']='Bearer '+token
            check('other-user DELETE403',client.delete(f'/api/analyses/{OTHER_ID}/video').status_code==403)
            before=client.get(f'/api/analyses/{ID}?include_series=true').json()
            pose=client.get(f'/api/analyses/{ID}/pose-3d').json()
            other=path.parents[1]/OTHER_ID/'original.mp4';other_hash=hashlib.sha256(other.read_bytes()).hexdigest()
            signed=client.get(f'/api/analyses/{ID}/video').json()['url']
            check('original file reachable before deletion',client.get(signed).status_code==200)
            asyncio.run(browse(socket_url,password,path,client))
            after=client.get(f'/api/analyses/{ID}?include_series=true').json()
            check('all score feedback input and date fields preserved',{k:v for k,v in before.items() if k!='video_status'}=={k:v for k,v in after.items() if k!='video_status'})
            response=client.get(f'/api/analyses/{ID}/pose-3d');check('pose API200 and payload preserved',response.status_code==200 and response.json()==pose)
            check('video GET410',client.get(f'/api/analyses/{ID}/video').status_code==410)
            check('previous local capability cannot fetch file',client.get(signed).status_code in (404,410))
            rows=client.get('/api/users/video-delete-ui/swings').json()['items']
            check('trend and calendar retain score date and analysis ID',len(rows)==1 and rows[0]['analysis_id']==ID and rows[0]['score']==before['result']['overall']['score'] and rows[0]['video_status']=='deleted')
            check('other users original preserved',other.exists() and hashlib.sha256(other.read_bytes()).hexdigest()==other_hash)
            repeated=client.delete(f'/api/analyses/{ID}/video');check('repeat DELETE succeeds idempotently',repeated.status_code==200 and repeated.json()['already_deleted'])
        REPORT['status']='passed'
    except Exception as e:
        REPORT['status']='failed';REPORT['failure']=str(e);raise
    finally:
        for proc,created in reversed(owned):stop_owned(proc,created)
        server.shutdown();server.server_close()
        (OUT/'browser-validation.json').write_text(json.dumps(REPORT,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'status':REPORT.get('status'),'checks':len(REPORT['checks']),'fixture_only':True,'owned_servers_stopped':True}))


if __name__=='__main__':main()
