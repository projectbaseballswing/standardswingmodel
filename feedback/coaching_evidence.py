"""Read-only coaching evidence contract. No inference, credentials, or I/O.

Ranking mirrors stage-3A: eligible phase |z|, deterministic ties, one phase per
joint. Strict explicit availability adds fail-closed handling for legacy data.
"""
from __future__ import annotations
from collections import Counter
import math

PARTS={'lead_arm','rear_arm','torso','lead_leg','rear_leg'}
PHASES={'stride','transition','swing','follow'}
# Model 0.2 feature contract, not names inferred from untrusted report strings.
FEATURE_PART={
 'lead_elbow_angle':'lead_arm','hand_x_from_shoulder':'lead_arm','hand_y_from_shoulder':'lead_arm',
 'rear_elbow_angle':'rear_arm','lead_knee_angle':'lead_leg','lead_ankle_x_from_hip':'lead_leg',
 'lead_ankle_y_from_hip':'lead_leg','rear_knee_angle':'rear_leg',
 **{k:'torso' for k in ('torso_lean','shoulder_tilt','hip_tilt','shoulder_x_from_hip','shoulder_y_from_hip','shoulder_turn','hip_turn','hip_shoulder_separation')},
}
UNMEASURED=['시선','머리 움직임','힘·근력·지면 반력','회전 시작 순서','배트 궤적','원인과 교정 효과']
SEMANTICS={
 'torso_lean':'수직 기준 기울기: +는 투수 쪽, -는 포수 쪽. 기준도 기울 수 있으며 목표 0도가 아님.',
 'shoulder_tilt':'어깨선 기울기: 커지면 뒤 어깨가 더 내려감. 회전 순서 아님.',
 'hip_tilt':'골반선 기울기: 커지면 뒤 골반이 더 내려감.',
 'hand_x_from_shoulder':'어깨 기준 손 위치: +는 투수 쪽. 위치 차이는 조기 출발·속도를 뜻하지 않음.',
 'hand_y_from_shoulder':'어깨 기준 손 높이: 커지면 더 높음.',
 'lead_ankle_x_from_hip':'골반 기준 앞발 거리: 커지면 더 멀리 나감.',
 'lead_ankle_y_from_hip':'골반 기준 앞발 높이: 커지면 더 높게 들림.',
 'shoulder_x_from_hip':'골반 기준 상체 위치: +는 투수 쪽.',
 'shoulder_y_from_hip':'골반 기준 상체 높이: 커지면 더 높음.',
 'shoulder_turn':'어깨의 열림 각도, 회전 시작 순서는 측정하지 않음.',
 'hip_turn':'골반의 열림 각도, 힘·회전 시작 순서는 측정하지 않음.',
 'hip_shoulder_separation':'어깨·골반 각도 차이: 커지면 어깨가 더 열려 꼬임이 덜함. 힘을 측정하지 않음.',
 **{k:'어깨/골반-팔꿈치/무릎-손목/발목 각도: 커지면 더 펴짐, 작아지면 더 굽힘. 힘은 측정하지 않음.' for k in ('lead_elbow_angle','rear_elbow_angle','lead_knee_angle','rear_knee_angle')},
}

def finite(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def number(v):return v if finite(v) else None
def score(v):return v if finite(v) and 0<=v<=100 else None
def rows(v):return [x for x in v if isinstance(x,dict)] if isinstance(v,list) else []
def obj(v):return v if isinstance(v,dict) else {}
def quality(v):return v.get('available') is True and v.get('reliability') in ('high','medium')
def version(r):
    v=r.get('model_version') or obj(r.get('overall')).get('model_version')
    return v if isinstance(v,str) else None
def safe_text(v):return v[:300] if isinstance(v,str) else ''

def unique(v,key,allowed,kind,excluded):
    items=rows(v);counts=Counter(x.get(key) for x in items if isinstance(x.get(key),str))
    out={}
    for x in items:
        k=x.get(key)
        if not isinstance(k,str) or k not in allowed or counts[k]!=1:
            excluded.append({'kind':kind,'key':safe_text(k),'name':safe_text(x.get('name')),'reason':'unknown_or_duplicate_key'})
        else:out[k]=x
    return out

def score_basis(r):
    o=obj(r.get('overall'));p,s,t=[score(o.get(k)) for k in ('posture_score','speed_score','score')]
    v=version(r);known=isinstance(v,str) and v.startswith('0.2')
    verified=known and quality(o) and all(x is not None and 0<=x<=100 for x in (p,s,t)) and round(.7*p+.3*s,1)==t
    only=known and quality(o) and p is not None and 0<=p<=100 and o.get('speed_score') is None and t==p
    return {'model_version':v,'overall_score':t,'posture_score':p,'speed_score':s,
      'verified_composition':verified,'weights':{'posture':.7,'speed':.3} if verified else None,
      'posture_only':only,'posture_capped':o.get('posture_capped') is True,
      'explanation_status':'verified' if verified or only else 'insufficient_or_inconsistent',
      'meaning':'자세는 표준화 곡선 차이의 RMS 거리에서 환산, 속도는 임팩트 주변 최대 손 속도. 부위 점수 평균·부위 감점 기여도·배트/타구 속도가 아님.'}

def phase_evidence(p,j,phase):
    if p.get('available') is not True or p.get('level') not in ('good','caution','warning'):return None
    if not all(finite(p.get(k)) for k in ('user_mean','reference_mean','diff','z_score')):return None
    # Values in stored reports are rounded separately to one decimal.
    if abs((p['user_mean']-p['reference_mean'])-p['diff'])>.151:return None
    if p.get('direction') not in ('higher','lower','similar'):return None
    z=abs(p['z_score'])
    if p['level']=='good' and z>1.01:return None
    if p['level']=='caution' and not .99<=z<=2.01:return None
    if p['level']=='warning' and z<1.99:return None
    # diff is a difference of phase means; z is the mean of per-time
    # standardized differences. Different signs are mathematically possible.
    if p['level']=='good' and p['direction']!='similar':return None
    if p['level']!='good' and (p.get('direction') not in ('higher','lower') or (p['diff']>0)!=(p['direction']=='higher')):return None
    return {'joint':j['key'],'key':p['phase'],'phase':p['phase'],'phase_name':safe_text(phase.get('name')),
      'name':safe_text(j.get('name')),'part':j['body_part'],'unit':safe_text(j.get('unit')),
      'user':p['user_mean'],'reference':p['reference_mean'],'diff':p['diff'],'z_score':p['z_score'],
      'level':p['level'],'direction':p.get('direction'),'direction_text':safe_text(p.get('direction_text')),
      'reliability':j['reliability'],'phase_reliability':phase['reliability'],
      'evidence_id':f"joints.{j['key']}.phases.{p['phase']}",
      'limit':'구간 평균이며 전 프레임의 자세·추적 안정성을 뜻하지 않음'}

def measured_event(v):
    v=obj(v)
    if not all(finite(v.get(k)) for k in ('user','reference','diff','z_score')):return None
    if abs(v['user']-v['reference']-v['diff'])>.151:return None
    if v.get('level') not in ('good','caution','warning'):return None
    return {k:v.get(k) for k in ('user','reference','diff','z_score','level')}

def measured_range(v):
    """ROM has user/reference/diff, not an impact z or severity contract."""
    v=obj(v)
    if not all(finite(v.get(k)) for k in ('user','reference','diff')):return None
    if v['user']<0 or v['reference']<0 or abs(v['user']-v['reference']-v['diff'])>.151:return None
    return {k:v[k] for k in ('user','reference','diff')}

def rank(observations,issue):
    found=[x for x in observations if (x['level']!='good')==issue]
    found.sort(key=lambda x:((-1 if issue else 1)*abs(x['z_score']),x['joint'],x['phase']))
    seen=set();result=[]
    for x in found:
        if x['joint'] not in seen:result.append(x);seen.add(x['joint'])
    return result

def build_evidence_input(report,*,scope='overall',previous=None):
    if scope not in ('overall','full'):raise ValueError('Unknown coaching scope')
    r=obj(report);o=obj(r.get('overall'));excluded=[]
    groups=unique(o.get('group_scores'),'key',PARTS,'part',excluded)
    phases=unique(obj(r.get('phases')).get('phases'),'key',PHASES,'phase',excluded)
    joints=unique(r.get('joints'),'key',set(FEATURE_PART),'joint',excluded)
    good_phases={k:p for k,p in phases.items() if quality(p) and quality(o)}
    for k,p in phases.items():
        if k not in good_phases:excluded.append({'kind':'phase','key':k,'name':safe_text(p.get('name')),'reason':'quality_or_availability'})
    parts={};flat=[];observations=[]
    for k,g in groups.items():
        if quality(g) and quality(o):
            part_score=score(g.get('score'))
            parts[k]={'key':k,'name':safe_text(g.get('name')),'score':part_score,'reliability':g['reliability'],
                'status':'잘함' if part_score is not None and part_score>=80 else '개선필요' if part_score is not None else '판정 보류',
                'status_limit':'점수 표시용 상태이며 교정 유무·전 구간 안정성을 뜻하지 않음','features':[]}
        else:excluded.append({'kind':'part','key':k,'name':safe_text(g.get('name')),'reason':'quality_or_availability'})
    for k,j in joints.items():
        if not quality(j) or j.get('unit') not in ('deg','body') or not isinstance(j.get('body_part'),str) or j.get('body_part') not in parts or j.get('body_part')!=FEATURE_PART[k]:
            excluded.append({'kind':'joint','key':k,'name':safe_text(j.get('name')),'reason':'quality_or_part_mapping'});continue
        pp=unique(j.get('phases'),'phase',PHASES,'joint_phase',excluded);ee=[]
        for pk,p in pp.items():
            e=phase_evidence(p,j,good_phases[pk]) if pk in good_phases else None
            if e:ee.append(e)
            else:excluded.append({'kind':'joint_phase','key':k+'.'+pk,'name':safe_text(j.get('name')),'reason':'unreliable_missing_or_inconsistent_measurement'})
        if not ee:
            excluded.append({'kind':'joint','key':k,'name':safe_text(j.get('name')),'reason':'no_reliable_phase'});continue
        # No unverified biological mechanisms from old feature descriptions.
        item={'key':k,'name':safe_text(j.get('name')),'body_part':j['body_part'],'unit':safe_text(j.get('unit')),'measurement_semantics':SEMANTICS[k],
              'reliability':j['reliability'],'phases':ee,'impact':measured_event(j.get('impact')),
              'range_of_motion':measured_range(j.get('range_of_motion'))}
        item['impact_diff']=item['impact']['diff'] if item['impact'] else None
        item['range_of_motion_diff']=item['range_of_motion']['diff'] if item['range_of_motion'] else None
        flat.append(item);parts[j['body_part']]['features'].append(item);observations.extend(ee)
    parts={k:p for k,p in parts.items() if p['features']}
    phase_lines=[]
    for k,p in good_phases.items():
        relevant=sorted([x for x in observations if x['phase']==k and x['level']!='good'],key=lambda x:(-abs(x['z_score']),x['joint']))
        u,ref=number(p.get('user_duration_ms')),number(p.get('reference_duration_ms'))
        valid_time=u is not None and ref is not None and u>0 and ref>0
        phase_lines.append({'key':k,'name':safe_text(p.get('name')),'score':score(p.get('score')),'reliability':p['reliability'],
          'user_duration_ms':u if valid_time else None,'reference_duration_ms':ref if valid_time else None,
          'tempo_level':p.get('tempo_level') if valid_time and p.get('tempo_level') in ('good','caution','warning') else None,
          'tempo_ratio':round(u/ref,3) if valid_time else None,
          'top_deviation':relevant[0] if relevant else None})
    result={'contract':'coaching-evidence-v1','overall_score':score(o.get('score')),'reliability':o.get('reliability') if isinstance(o.get('reliability'),str) else None,
      'score_basis':score_basis(r),'parts':list(parts.values()),'priority_candidates':rank(observations,True)[:3],
      'strengths':rank(observations,False)[:2],'observations':observations,'tempo_evidence':phase_lines,
      'allowed':{'parts':list(parts),'joints':[j['key'] for j in flat],'phases':[p['key'] for p in phase_lines]},
      'excluded':excluded,'not_measured':UNMEASURED.copy(),
      'priority_policy':'3-A: explicit high/medium at overall/part/joint/phase, finite measurements; |z| descending, joint+phase tie break, unique joint. Not score contribution.',
      'comparison':{'available':False,'reason':'previous_report_not_provided'},
      'rotation_issues':[]}
    # Retain measured rotation magnitudes only; omit prior free-text causal messages.
    if quality(o) and 'torso' in parts:
        for c in rows(o.get('rotation_checks')):
            if c.get('key') in ('hip_opens','shoulder_opens','separation_at_plant','separation_releases') and finite(c.get('value')):
                result['rotation_issues'].append({'key':c['key'],'name':safe_text(c.get('name')),'value':c['value'],
                     'unit':safe_text(c.get('unit')),'passed':c.get('passed') if isinstance(c.get('passed'),bool) else None,
                     'affects_score':c.get('affects_score') if isinstance(c.get('affects_score'),bool) else None})
    if scope=='full':result.update(joints=flat,phases=phase_lines)
    if previous is not None:result['comparison']=comparison_evidence(r,obj(previous),result)
    return result

def comparison_evidence(current,previous,current_payload):
    # Same stored model required. This is a score comparison, not proof of pose improvement.
    if not version(current) or version(current)!=version(previous):return {'available':False,'reason':'model_version_missing_or_different'}
    if not quality(obj(previous.get('overall'))) or not quality(obj(current.get('overall'))):return {'available':False,'reason':'overall_quality'}
    for key in ('handedness','reference_id'):
        if current.get(key)!=previous.get(key):return {'available':False,'reason':key+'_mismatch'}
    old=build_evidence_input(previous,scope='full');cur=current_payload
    a,b=cur['overall_score'],old['overall_score']
    if a is None or b is None:return {'available':False,'reason':'missing_score'}
    result={'available':True,'model_version':version(current),'overall':{'current_score':a,'previous_score':b,'delta':round(a-b,1)},
            'parts':[],'joints':[],'phases':[],
            'condition_match_verified':False,
            'metadata_missing':[k for k in ('handedness','reference_id') if current.get(k) is None or previous.get(k) is None],
            'limitations':['촬영 조건·동일 사용자 여부는 호출부가 확인해야 함','점수 변화는 실제 자세·타격 성과 개선을 보장하지 않음']}
    prior={p['key']:p for p in old['parts']}
    for p in cur['parts']:
        q=prior.get(p['key'],{});x,y=p['score'],q.get('score');delta=round(x-y,1) if finite(x) and finite(y) else None
        result['parts'].append({'key':p['key'],'name':p['name'],'current_score':x,'previous_score':y,'delta':delta,
          'status':'비교불가' if delta is None else '개선' if delta>2 else '악화' if delta< -2 else '유지'})
    old_joint={j['key']:j for j in old['joints']}
    for j in [j for p in cur['parts'] for j in p['features']]:
        q=old_joint.get(j['key'],{});a,b=j['impact_diff'],q.get('impact_diff');x,y=j['range_of_motion_diff'],q.get('range_of_motion_diff')
        if not q:continue
        result['joints'].append({'key':j['key'],'name':j['name'],'body_part':j['body_part'],'current_diff':a,'previous_diff':b,
             'gap_narrowed':round(abs(b)-abs(a),1) if finite(a) and finite(b) else None,
             'rom_gap_narrowed':round(abs(y)-abs(x),1) if finite(x) and finite(y) else None})
    old_phase={p['key']:p for p in old['phases']}
    for p in cur['tempo_evidence']:
        q=old_phase.get(p['key'],{});x,y=p['score'],q.get('score');delta=round(x-y,1) if finite(x) and finite(y) else None
        result['phases'].append({**p,'current_score':x,'previous_score':y,'delta':delta,'status':'비교불가' if delta is None else '개선' if delta>2 else '악화' if delta< -2 else '유지'})
    return result
