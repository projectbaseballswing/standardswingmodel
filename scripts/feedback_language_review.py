"""Offline CSV/replay audit and fixture preparation; no API, DB or SDK imports."""
import argparse
from collections import Counter, defaultdict
import copy
import csv
import hashlib
import html
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.local/feedback-language'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def write(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def prepare(args):
    OUT.mkdir(parents=True,exist_ok=True)
    baseline=Path(args.baseline)
    inputs=Path(args.inputs)
    source=Path(args.csv)
    rows=list(csv.DictReader(source.open(encoding='utf-8-sig',newline='')))
    assert all(k in rows[0] for k in ['원문','내 수정문','메모','검토 상태','원문 위치'])
    protected=[source,inputs,baseline/'.local/feedback-stage3e/flutter-replay.json']
    protected += list((baseline/'feedback').glob('*.py'))+list((baseline/'api').glob('*.py'))
    protected += list((baseline/'frontend/lib').rglob('*.dart'))
    write(OUT/'protected.json',{str(p):sha(p) for p in protected})
    write(OUT/'csv-review.json',rows)
    cases=read(inputs);assert len(cases)==6
    write(OUT/'inputs.json',cases)
    write(OUT/'before.json',read(baseline/'.local/feedback-stage3e/flutter-replay.json'))
    demo=copy.deepcopy(cases)
    for row in demo:
        row['label']='저장 리포트 · '+row['id']
        row['body'].update(analysis_id=row['id'],video_status='deleted')
    low=copy.deepcopy(demo[0]);low['id']='low_drop';low['label']='합성 비교 · 저신뢰 90 → 20점'
    low['body']['analysis_id']='low_drop'
    groups=low['body']['result']['overall']['group_scores']
    for g in groups:
        if g['key']=='rear_arm':g.update(score=20.0,reliability='low')
    previous={g['key']:g['score'] for g in groups}
    previous.update(rear_arm=90.0,lead_arm=65.0,torso=90.0)
    low['comparison']={'has_previous':True,'overall_previous_score':70,
        'parts':[{'key':g['key'],'previous_score':previous[g['key']]} for g in groups]}
    demo.append(low);write(OUT/'review-fixtures.json',demo)
    print(json.dumps({'rows':len(rows),'sources':dict(Counter(r['출처'] for r in rows)),'replay_cases':6,'synthetic_ui_cases':1},ensure_ascii=False))

def key(r):return (r['section'],r['slot'],r.get('source_target',r['target']))
def report():
    before=read(OUT/'before.json');after=read(OUT/'after.json')
    a={c['id']:c for c in after};b={c['id']:c for c in before}
    assert len(a)==len(b)==6
    for identifier,case in b.items():
        assert case['score_snapshot']==a[identifier]['score_snapshot'],identifier
        assert a[identifier]['input_unchanged'] and not a[identifier]['coaching_present']
    mapped={};diffs=[]
    for identifier,case in b.items():
        targets=defaultdict(list)
        for row in a[identifier]['rows']:targets[key(row)].append(row)
        seen=Counter()
        for i,row in enumerate(case['rows']):
            k=key(row);idx=seen[k];seen[k]+=1
            candidates=targets.get(k,[])
            replacement=candidates[idx] if idx<len(candidates) else None
            mapped[(identifier,i)]=replacement
            diffs.append({'case':identifier,'section':row['section'],'slot':row['slot'],'target':row['target'],
                'before':row['text'],'after':replacement['text'] if replacement else '중복 안내를 합치거나 표시에서 제외',
                'changed':replacement is None or row['text']!=replacement['text']})
    rows=read(OUT/'csv-review.json');review=[]
    for r in rows:
        new=[]
        for identifier,index in re.findall(r'서비스 재생 · ([^:| ]+):rows\[(\d+)\]',r['원문 위치']):
            item=mapped.get((identifier,int(index)))
            if item and item['text'] not in new:new.append(item['text'])
        source=r['출처']
        if source=='gpt':
            decision='향후 GPT 문체 검토 참고 · 과거 응답/프롬프트/승인 정책 미변경'
        elif source=='report':
            decision='저장 리포트 보존 · 알려진 항목 정의·알림만 표시 단계에서 변환 (일괄 치환 아님)'
        else:decision='실제 생성 함수에 연결해 템플릿 반영 · 반복 안내 축약'
        review.append(dict(r,반영방식=decision,현재표시예시='\n\n'.join(new[:3])))
    site=OUT/'site';site.mkdir(exist_ok=True)
    write(site/'review.json',review);write(OUT/'replay-diff.json',diffs)
    with (site/'review-mapping.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(review[0]));writer.writeheader();writer.writerows(review)
    assert all(sha(Path(p))==v for p,v in read(OUT/'protected.json').items())
    summary={'source_counts':dict(Counter(r['출처'] for r in rows)),'cases':6,'scores_equal':True,
        'raw_inputs_unchanged':True,'protected_files_unchanged':True,'new_openai_requests':0,
        'replay_rows':len(diffs),'changed_replay_rows':sum(d['changed'] for d in diffs)}
    write(OUT/'summary.json',summary)
    payload=json.dumps(review,ensure_ascii=False).replace('<','\\u003c')
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>StandardSwing 문구 개선 검토</title>
<style>body{margin:24px auto;padding:0 18px;max-width:1150px;font:16px system-ui;color:#173c35;background:#f4f8f6}p{line-height:1.6}article{background:white;border:1px solid #ceddd5;border-radius:12px;padding:18px;margin:14px 0}pre{white-space:pre-wrap;font:inherit;line-height:1.65}select,input,button{font:inherit;padding:9px;margin:4px}nav{position:sticky;top:0;background:#f4f8f6;padding:12px}small{color:#576c63}.after{border-left:4px solid #278665;padding:10px;background:#eef8f1}</style>
<h1>사용자 피드백 문구 개선</h1><p>CSV 수정안과 실제 Flutter 표시 결과를 비교합니다. 기존 6개 리포트의 점수는 동일하며 GPT 추가 호출은 없습니다.<br>문구의 자연스러움은 추가 사용자 검토가 필요합니다. CSV 제안을 수치나 교정 지시로 그대로 치환하지 않았습니다.</p>
<p><a href="app/">실제 Flutter 검토 화면 열기</a> · <a href="review-mapping.csv" download>원문·수정안·표시 결과 CSV</a></p>
<nav><select id="source"><option>service</option><option>report</option><option>gpt</option><option>all</option></select><input id="q" placeholder="골반, 앞발, 팔꿈치 등 검색"><span id="count"></span></nav><div id="rows"></div><button id="more">다음 30개 표시</button>
<script>const data=PAYLOAD;const $=id=>document.getElementById(id);let limit=30;
const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function draw(){const rows=data.filter(r=>($('source').value==='all'||r['출처']===$('source').value)&&JSON.stringify(r).includes($('q').value));$('count').textContent=rows.length+'개';$('rows').innerHTML=rows.slice(0,limit).map(r=>`<article><small>${esc(r['출처'])} · ${esc(r['분류'])} · ${esc(r['검토 상태'])}</small><h3>기존 원문</h3><pre>${esc(r['원문'])}</pre><h3>사용자 수정안</h3><pre>${esc(r['내 수정문'])}</pre><p>${esc(r['반영방식'])}</p>${r['현재표시예시']?`<div class="after"><b>실제 새 표시 문맥</b><pre>${esc(r['현재표시예시'])}</pre></div>`:''}<details><summary>메모와 원문 위치</summary><pre>${esc(r['메모'])}</pre><small>${esc(r['원문 위치'])}</small></details></article>`).join('');$('more').hidden=limit>=rows.length;}
for(const id of ['source','q'])$(id).oninput=()=>{limit=30;draw()};$('more').onclick=()=>{limit+=30;draw()};draw();</script></html>'''
    (site/'index.html').write_text(page.replace('PAYLOAD',payload),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','report']);p.add_argument('--csv');p.add_argument('--baseline');p.add_argument('--inputs');args=p.parse_args()
    prepare(args) if args.mode=='prepare' else report()
