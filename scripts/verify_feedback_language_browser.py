"""Inspect the actual Flutter widgets using local fixtures only. No backend."""
import asyncio
import base64
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import websockets

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.local/feedback-language'
SITE='http://127.0.0.1:9005'
CDP=9576
sys.path.insert(0,str(ROOT/'scripts'))
from verify_original_video_delete_browser import Browser as BaseBrowser

class Browser(BaseBrowser):
    def __init__(self,ws):
        self.urls=[];self.errors=[]
        super().__init__(ws)
    async def receive(self):
        async for raw in self.ws:
            msg=json.loads(raw)
            if 'id' in msg:
                future=self.pending.pop(msg['id'],None)
                if future and not future.done():future.set_result(msg)
            elif msg.get('method')=='Network.requestWillBeSent':self.urls.append(msg['params']['request']['url'])
            elif msg.get('method')=='Runtime.exceptionThrown':self.errors.append(msg['params'])
    async def mouse(self,x,y):
        await self.call('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x,'y':y})
        await asyncio.sleep(.2)
        await super().mouse(x,y)
    async def content(self):return await self.js("document.body.innerText+'\\n'+[...document.querySelectorAll('[aria-label]')].map(e=>e.getAttribute('aria-label')).join('\\n')")
    async def tap(self,label,contains=False):
        # Match the node's own label; ancestor innerText includes off-screen descendants.
        expression="""(()=>{const label=LABEL;const es=[...document.querySelectorAll('flt-semantics,[aria-label]')].filter(e=>{
          const aria=e.getAttribute('aria-label');if(!aria&&e.querySelector('flt-semantics,[aria-label]'))return false;
          const t=(aria||e.innerText||'').replace(/\\s+/g,' ').trim();const r=e.getBoundingClientRect();
          return r.width>0&&r.height>0&&r.top>=0&&r.bottom<=innerHeight&&(PART?t.includes(label):(t===label||t.startsWith(label+' Tab ')));
        });es.sort((a,b)=>a.getBoundingClientRect().width*a.getBoundingClientRect().height-b.getBoundingClientRect().width*b.getBoundingClientRect().height);
        const e=es[0];if(!e)return null;const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()"""
        result=await self.js(expression.replace('LABEL',json.dumps(label)).replace('PART',str(contains).lower()))
        if result is None:raise AssertionError('Missing visible control: '+label)
        with (OUT/'chrome-actions.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'label':label,'position':result,'url':await self.js('location.href')},ensure_ascii=False)+'\n')
        await self.mouse(**result);await asyncio.sleep(.6)
    async def wheel(self,dy):
        await self.call('Input.dispatchMouseEvent',{'type':'mouseWheel','x':210,'y':650,'deltaY':dy,'deltaX':0});await asyncio.sleep(.3)
    async def locate(self,text):
        for _ in range(14):
            try:return await self.tap(text,True)
            except AssertionError:await self.wheel(420)
        raise AssertionError('Cannot find '+text)
    async def shot(self,name):
        result=await self.call('Page.captureScreenshot',{'format':'png'})
        p=OUT/'site/screenshots';p.mkdir(exist_ok=True)
        (p/(name+'.png')).write_bytes(base64.b64decode(result['data']))

checks=[]
def check(name,condition):
    checks.append({'name':name,'passed':bool(condition)})
    (OUT/'chrome-validation.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    print(('PASS ' if condition else 'FAIL ')+name,flush=True)
    assert condition,name

def start():
    try:
        body=urllib.request.urlopen(SITE,timeout=2).read()
        assert body==(OUT/'site/index.html').read_bytes(),'Port used by another app'
    except urllib.error.URLError:
        with socket.socket() as probe:probe.bind(('127.0.0.1',9005))
        log=(OUT/'server.log').open('ab')
        p=subprocess.Popen([sys.executable,'-B','-m','http.server','9005','--bind','127.0.0.1','--directory',str(OUT/'site')],
            stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        (OUT/'server.json').write_text(json.dumps({'pid':p.pid,'url':SITE}),encoding='utf-8')
    try:return json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version',timeout=2))
    except OSError:
        log=(OUT/'chrome.log').open('ab')
        p=subprocess.Popen(['C:/Program Files/Google/Chrome/Application/chrome.exe',f'--remote-debugging-port={CDP}',
            '--remote-debugging-address=127.0.0.1','--user-data-dir='+str(OUT/'chrome'),
            '--no-first-run','--no-default-browser-check','--disable-background-networking','about:blank'],stdout=log,stderr=log)
        (OUT/'browser.json').write_text(json.dumps({'pid':p.pid,'cdp':CDP}),encoding='utf-8')
        for _ in range(60):
            try:return json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version',timeout=1))
            except OSError:time.sleep(.2)
        raise RuntimeError('Chrome did not start')

async def main():
    version=start()
    async with websockets.connect(version['webSocketDebuggerUrl'],max_size=32_000_000) as ws:
        b=Browser(ws)
        try:target=(await b.call('Target.createTarget',{'url':'about:blank'}))['targetId']
        finally:b.reader.cancel();await asyncio.gather(b.reader,return_exceptions=True)
    pages=json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json'))
    page=next(p for p in pages if p['id']==target)
    async with websockets.connect(page['webSocketDebuggerUrl'],max_size=32_000_000) as ws:
        b=Browser(ws)
        try:
            for domain in ['Page','Runtime','Network']:await b.call(domain+'.enable')
            await b.call('Page.bringToFront')
            await b.call('Emulation.setFocusEmulationEnabled',{'enabled':True})
            await b.call('Emulation.setDeviceMetricsOverride',{'width':430,'height':1000,'deviceScaleFactor':1,'mobile':False})
            await b.call('Page.navigate',{'url':SITE+'/app/'})
            await b.wait_text('종합 피드백')
            await asyncio.sleep(.5)
            check('Actual Flutter review app loads synthetic low comparison', '저신뢰 90' in await b.content())
            await b.locate('측정 확인 필요');await b.shot('01-overall-neutral')
            text=await b.content()
            check('Low scores remain reference-only with no -70 drop badge','이전 90점 · 현재 20점' in text and '(-70)' not in text)
            await b.tap('상세 피드백 보기',True);await b.wait_text('관절별 분석')
            await b.tap('오른쪽 팔',True);await asyncio.sleep(.5)
            await b.locate('이전 점수 · 참고');await b.shot('02-joint-neutral')
            text=await b.content()
            check('Joint view suppresses change judgment and shows both reference scores', '현재 점수 · 참고' in text and '점수 변화' not in text)
            # Open a saved case by the actual dropdown, then inspect the new unit details.
            await b.tap('합성 비교 · 저신뢰',True);await asyncio.sleep(.2)
            await b.tap('저장 리포트 · sample',True);await b.wait_text('종합 피드백');await asyncio.sleep(1)
            await b.tap('상세 피드백 보기',True);await b.wait_text('관절별 분석')
            await b.tap('몸통',True);await asyncio.sleep(.3)
            await b.locate('측정 항목과 단위 보기');await asyncio.sleep(.3)
            check('Hip details explain image tilt, not a horizontal correction target','수평으로 맞추라는 뜻은 아니에요' in await b.content())
            await b.shot('03-hip-details')
            await b.wheel(-5000);await b.tap('왼쪽 다리',True);await asyncio.sleep(.3)
            await b.locate('골반 기준 앞발 위치');await asyncio.sleep(.3)
            await b.locate('측정 항목과 단위 보기');await asyncio.sleep(.3)
            check('Foot details distinguish relative position from stride distance','실제로 앞발을 옮긴 거리가 아니에요' in await b.content())
            await b.shot('04-foot-details')
            await b.tap('저장 리포트 · sample',True);await b.tap('합성 비교 · 저신뢰',True);await b.wait_text('종합 피드백')
            await b.tap('구간별 피드백 보기',True);await b.wait_text('구간별 피드백')
            await b.locate('분석 결과 안내 · 기본 설명');await b.shot('05-phase-guidance')
            check('Phase view displays basic measured guidance','원본 영상' in await b.content())
            check('No browser JS errors',not b.errors)
            check('No backend, OpenAI or Supabase request',not any('/api/' in u or 'openai.com' in u or 'supabase.co' in u for u in b.urls))
            await b.call('Page.navigate',{'url':SITE+'/'})
            await asyncio.sleep(.5)
            check('CSV review index lists all service rows',await b.js("document.getElementById('count').textContent==='215개'"))
            await b.shot('06-wording-review')
        except Exception:
            await b.shot('browser-failure')
            (OUT/'chrome-failure-text.txt').write_text(await b.content(),encoding='utf-8')
            raise
        finally:
            (OUT/'chrome-network.json').write_text(json.dumps({'urls':b.urls,'runtime_errors':len(b.errors)},ensure_ascii=False,indent=2),encoding='utf-8')
            b.reader.cancel();await asyncio.gather(b.reader,return_exceptions=True)
    print(json.dumps({'report':SITE,'app':SITE+'/app/','checks':len(checks),'passed':sum(c['passed'] for c in checks)},ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
