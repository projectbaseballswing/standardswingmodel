"""Chrome UI regression with real local FastAPI/SQLite and labelled test fixtures.

Never connects to Supabase or runs inference. Run with the existing development
Python after `flutter build web --no-web-resources-cdn
--dart-define=API_BASE_URL=http://127.0.0.1:8897`. All private output is .local/.
"""
from __future__ import annotations
import asyncio,base64,copy,json,os,secrets,subprocess,sys,threading,time,urllib.request
from datetime import datetime,timedelta,timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import httpx,psutil,websockets

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.local/swing-trend';WEB=ROOT/'frontend/build/web';SITE='http://127.0.0.1:8971';API='http://127.0.0.1:8897';CDP=9547
SHOTS=ROOT/'docs/screenshots/swing-trend';REPORT={'fixture_only':True,'backend':'Unmodified FastAPI + isolated SQLite; no Supabase/inference','checks':[],'api_responses':[],'runtime_errors':[]}

def environment(folder):
    env=dict(os.environ)
    env.update(DATABASE_URL='sqlite:///'+str(folder/'fixture.db'),SWING_DATABASE_SCHEMA='public',SWING_MOCK='1',SWING_WORKER_ID='trend-ui-local-check',SWING_STORAGE_BACKEND='local',SWING_LOCAL_STORAGE_ROOT=str(folder/'storage'),SUPABASE_URL='',SUPABASE_SERVICE_ROLE_KEY='',SUPABASE_STORAGE_BUCKET='',OPENAI_API_KEY='',PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1')
    return env

def seed(password):
    sys.path.insert(0,str(ROOT))
    from api.database import Base,User,Swing,SessionLocal,engine
    from api.security import hash_password
    if engine.url.get_backend_name() != 'sqlite' or not Path(engine.url.database).resolve().is_relative_to(OUT.resolve()):
        raise RuntimeError('Browser verification requires its isolated local SQLite database')
    Base.metadata.create_all(engine)
    fixture=json.loads((ROOT/'frontend/test/fixtures/analysis_v2.json').read_text(encoding='utf-8'))['result']
    now=datetime.now(timezone.utc)-timedelta(hours=1)
    with SessionLocal() as db:
        for name in ['trend-ui-check','trend-ui-empty','trend-ui-single','trend-ui-no-score','trend-ui-other']:
            db.add(User(user_id=name,email=name+'@example.invalid',nickname=name,password_hash=hash_password(password)))
        db.flush()
        def add(name,identifier,days,score,status='done'):
            result=copy.deepcopy(fixture);result['overall']['score']=score
            result['overall']['summary']='화면 검증용 합성 테스트 기록입니다.'
            db.add(Swing(analysis_id=identifier,user_id=name,recorded_at=now-timedelta(days=days),created_at=now-timedelta(days=days),worker_id='fixture-only',status=status,input={'handedness':'right'},result=result if status=='done' else None))
        for i,(days,score) in enumerate([(0,82.4),(1,79),(3,81.2),(5,75.8),(8,73.1),(13,76.5),(21,68.7),(29,63.5),(45,61.2)]):add('trend-ui-check',f'trend-fixture-{i}',days,score)
        add('trend-ui-check','trend-fixture-working',1,None,'processing');add('trend-ui-check','trend-fixture-missing',2,None)
        add('trend-ui-single','trend-one',0,77.3);add('trend-ui-no-score','trend-none',0,None);add('trend-ui-other','trend-private-other',0,99)
        db.commit()
    engine.dispose()

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass

def check(name,condition):
    REPORT['checks'].append({'name':name,'passed':bool(condition)})
    if not condition:raise AssertionError(name)

class Browser:
    def __init__(self,ws):
        self.ws=ws;self.counter=0;self.pending={};self.reader=asyncio.create_task(self.receive())
    async def receive(self):
        async for raw in self.ws:
            m=json.loads(raw)
            if 'id' in m:
                f=self.pending.pop(m['id'],None)
                if f and not f.done():f.set_result(m)
            elif m.get('method')=='Runtime.exceptionThrown':REPORT['runtime_errors'].append(m['params'])
            elif m.get('method')=='Network.responseReceived':
                r=m['params']['response']
                if r['url'].startswith(API):REPORT['api_responses'].append({'path':r['url'].removeprefix(API),'status':r['status']})
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
            if text in (await self.js('document.body.innerText')):await asyncio.sleep(.35);return
            await asyncio.sleep(.15)
        raise AssertionError('Missing UI text: '+text)
    async def mouse(self,x,y):
        for kind in ['mousePressed','mouseReleased']:await self.call('Input.dispatchMouseEvent',{'type':kind,'x':x,'y':y,'button':'left','clickCount':1})
    async def tap(self,label,contains=False):
        result=await self.js("""(()=>{const label=LABEL;const es=[...document.querySelectorAll('flt-semantics')].filter(e=>{const t=(e.innerText||e.getAttribute('aria-label')||'').replace(/\\s+/g,' ').trim();const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&r.top>=0&&r.bottom<=innerHeight&&(PART?t.includes(label):(t===label||t.startsWith(label+' Tab ')))});es.sort((a,b)=>a.getBoundingClientRect().width*a.getBoundingClientRect().height-b.getBoundingClientRect().width*b.getBoundingClientRect().height);const e=es[0];if(!e)return null;const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()""".replace('LABEL',json.dumps(label)).replace('PART',str(contains).lower()))
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

async def browser_check(url,password):
    async with websockets.connect(url,max_size=64_000_000) as ws:
        b=Browser(ws)
        try:
            for d in ['Runtime','Page','Network']:await b.call(d+'.enable')
            await b.call('Emulation.setDeviceMetricsOverride',{'width':1280,'height':1100,'deviceScaleFactor':1,'mobile':False})
            await b.login('trend-ui-check',password);check('actual Flutter login via local FastAPI',True)
            await b.tap('스윙 추이');await b.wait_text('나의 스윙 점수 변화');await b.wait_text('기간 내 기록 8건')
            check('calendar tab opens trend /month8 scored records',True);await b.shot('desktop-month-fixture')
            check('all-history endpoint omitted month filters',any('/api/users/trend-ui-check/swings?' in r['path'] and 'year=' not in r['path'] and r['status']==200 for r in REPORT['api_responses']))
            await b.tap('최근 1주');await b.wait_text('기간 내 기록 4건');check('7day filter4records',True)
            await b.tap('전체');await b.wait_text('기간 내 기록 9건');check('all9records no generated dates',True)
            await b.tap('종합 피드백 보기',True);await b.wait_text('종합 피드백');await asyncio.sleep(.5)
            check('existing feedback loads selected analysis ID',any(r['path'].split('?')[0]=='/api/analyses/trend-fixture-0' and r['status']==200 for r in REPORT['api_responses']))
            # The existing GoRouter push flow does not reflect pushed routes in
            # the address bar. Use the feedback screen's existing back button.
            await b.mouse(28,28);await b.wait_text('나의 스윙 점수 변화');check('feedback returns to trend',True)
            await b.call('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':False});await asyncio.sleep(.6)
            await b.shot('mobile-all-fixture');check('390px mobile layout displayed',True)
            await b.call('Network.setBlockedURLs',{'urls':[API+'/api/users/*/swings*']});await b.tap('새로고침');await b.wait_text('기록을 불러오지 못했어요');await b.shot('mobile-error-fixture')
            await b.call('Network.setBlockedURLs',{'urls':[]});await b.tap('다시 시도');await b.wait_text('선택한 기록');check('offline error retry realHTTP',True)
            for user,text,shot in [('trend-ui-empty','아직 스윙 기록이 없어요','mobile-empty-fixture'),('trend-ui-no-score','표시할 종합 점수가 없어요','mobile-no-score-fixture'),('trend-ui-single','비교 전','mobile-single-fixture')]:
                await b.call('Page.navigate',{'url':'about:blank'});await b.login(user,password);await b.tap('스윙 추이');await b.wait_text(text);await b.shot(shot);check(user+' UI state',True)
            check('no Chrome runtime errors',not REPORT['runtime_errors'])
        except Exception:
            r=await b.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
            (OUT/'browser-failure.png').write_bytes(base64.b64decode(r['data']))
            raise
        finally:
            b.reader.cancel();await asyncio.gather(b.reader,return_exceptions=True)

def terminate_owned(proc,created):
    try:
        parent=psutil.Process(proc.pid)
        if parent.create_time()!=created:return
        children=parent.children(recursive=True)
        for p in children:
            try:p.terminate()
            except psutil.Error:pass
        parent.terminate();psutil.wait_procs(children+[parent],timeout=8)
    except psutil.Error:pass

def main():
    global SITE
    folder=OUT/('browser-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'));folder.mkdir(parents=True,exist_ok=False)
    os.environ.update(environment(folder));password=secrets.token_urlsafe(18);seed(password)
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(WEB)));SITE=f'http://127.0.0.1:{server.server_port}'
    threading.Thread(target=server.serve_forever,daemon=True).start();owned=[]
    try:
        for command,name in [([sys.executable,'-X','utf8','-B','-m','uvicorn','api.main:app','--host','127.0.0.1','--port','8897'],'api'),(['C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new',f'--remote-debugging-port={CDP}','--user-data-dir='+str(folder/'chrome'),'--no-first-run','--no-default-browser-check','about:blank'],'chrome')]:
            with (folder/(name+'.log')).open('w',encoding='utf-8') as log:proc=subprocess.Popen(command,cwd=ROOT,env=dict(os.environ),stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            owned.append((proc,psutil.Process(proc.pid).create_time()))
        for _ in range(150):
            if any(p.poll() is not None for p,_ in owned):raise RuntimeError('Owned child exited; see .local logs')
            try:
                with urllib.request.urlopen(API+'/api/health',timeout=1) as r:assert r.status==200
                pages=json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json',timeout=1));url=next(p['webSocketDebuggerUrl'] for p in pages if p['type']=='page');break
            except (OSError,StopIteration):time.sleep(.2)
        else:raise TimeoutError('Local startup')
        with httpx.Client(base_url=API,trust_env=False) as c:
            check('unauthenticated listing401',c.get('/api/users/trend-ui-check/swings').status_code==401)
            token=c.post('/api/login',json={'id':'trend-ui-check','password':password}).json()['access_token']
            check('other-user listing403',c.get('/api/users/trend-ui-other/swings',headers={'Authorization':'Bearer '+token}).status_code==403)
        asyncio.run(browser_check(url,password));REPORT['status']='passed'
    except Exception as e:
        REPORT['status']='failed';REPORT['failure']=str(e);raise
    finally:
        for p,t in reversed(owned):terminate_owned(p,t)
        server.shutdown();server.server_close();(OUT/'browser-validation.json').write_text(json.dumps(REPORT,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'status':REPORT.get('status'),'checks':len(REPORT['checks']),'fixture_only':True,'owned_servers_stopped':True}))

if __name__=='__main__':main()
