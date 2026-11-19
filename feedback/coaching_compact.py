"""Lossless normalization of canonical evidence, before LLM serialization.

One joint/observation copy, references for reused facts, column-labelled rows.
expand_coaching_input() exists for offline audits and proves no evidence loss.
"""
from copy import deepcopy

INHERITED={'name':'name','part':'body_part','unit':'unit','reliability':'reliability'}
DERIVED={'key','phase_name','phase_reliability','evidence_id',*INHERITED}

def compact_coaching_input(evidence):
    source=deepcopy(evidence)
    # Comparison-entry payload keeps legacy delta rows; the full current evidence
    # is passed through a separate canonical field by the caller.
    if 'canonical_evidence' in source:
        base=source.pop('canonical_evidence')
        return {'contract':'coaching-comparison-compact-v1','current':compact_coaching_input(base),'comparison_request':source}
    observations=source.pop('observations')
    obs_by_id={o['evidence_id']:o for o in observations}
    joint_map={j['key']:deepcopy(j) for p in source['parts'] for j in p['features']}
    phase_map={p['key']:p for p in source['tempo_evidence']}
    columns=[k for k in observations[0] if k not in DERIVED] if observations else []
    defaults={k:observations[0][k] for k in columns if all(o[k]==observations[0][k] for o in observations)} if observations else {}
    # Keep identity columns explicit even in a one-observation payload.
    defaults.pop('joint',None);defaults.pop('phase',None)
    columns=[k for k in columns if k not in defaults]
    table=[]
    for o in observations:
        j=joint_map[o['joint']];p=phase_map[o['phase']]
        assert o['key']==o['phase'] and o['phase_name']==p['name'] and o['phase_reliability']==p['reliability']
        assert o['evidence_id']==f"joints.{o['joint']}.phases.{o['phase']}"
        assert all(o[k]==j[v] for k,v in INHERITED.items())
        table.append([o[k] for k in columns])
    def ref(o):
        if o is None:return None
        assert obs_by_id[o['evidence_id']]==o
        return o['evidence_id']
    for j in joint_map.values():j['phases']=[ref(o) for o in j['phases']]
    for part in source['parts']:part['features']=[j['key'] for j in part['features']]
    source['priority_candidates']=[ref(o) for o in source['priority_candidates']]
    source['strengths']=[ref(o) for o in source['strengths']]
    for p in source['tempo_evidence']:p['top_deviation']=ref(p['top_deviation'])
    full='joints' in source
    full_joint_order=[]
    if full:
        original_joints=source.pop('joints')
        full_joint_order=[j['key'] for j in original_joints]
        assert {j['key']:j for j in original_joints}=={j['key']:j for p in evidence['parts'] for j in p['features']}
        assert evidence['phases']==evidence['tempo_evidence']
        source.pop('phases')
    original_contract=source.pop('contract')
    return {'contract':'coaching-evidence-compact-v1','original_contract':original_contract,'scope':'full' if full else 'overall',
      'reading_guide':'joint_table은 관절 정의/신뢰도/임팩트/움직임폭. observations의 columns 순서대로 rows를 읽는다. joint+phase는 joints.{joint}.phases.{phase} 근거 ID이며 우선/강점/구간 참조가 이를 가리킨다. name/part/unit/reliability는 joint_table, 구간 이름/신뢰도는 tempo_evidence에서 상속. defaults는 모든 행에 적용. 수치를 생략한 것이 아니다.',
      'full_joint_order':full_joint_order,'evidence':source,'joint_table':joint_map,'observations':{'columns':columns,'defaults':defaults,'rows':table}}

def expand_coaching_input(compact):
    c=deepcopy(compact)
    if c['contract']=='coaching-comparison-compact-v1':
        return {**c['comparison_request'],'canonical_evidence':expand_coaching_input(c['current'])}
    assert c['contract']=='coaching-evidence-compact-v1'
    source=c['evidence'];joints=c['joint_table'];phases={p['key']:p for p in source['tempo_evidence']}
    observations=[]
    for row in c['observations']['rows']:
        assert len(row)==len(c['observations']['columns'])
        o={**c['observations']['defaults'],**dict(zip(c['observations']['columns'],row))}
        j=joints[o['joint']];p=phases[o['phase']]
        o.update({k:j[v] for k,v in INHERITED.items()})
        o.update(key=o['phase'],phase_name=p['name'],phase_reliability=p['reliability'],evidence_id=f"joints.{o['joint']}.phases.{o['phase']}")
        observations.append(o)
    lookup={o['evidence_id']:o for o in observations}
    for j in joints.values():j['phases']=[deepcopy(lookup[i]) for i in j['phases']]
    for p in source['parts']:p['features']=[deepcopy(joints[i]) for i in p['features']]
    source['priority_candidates']=[deepcopy(lookup[i]) for i in source['priority_candidates']]
    source['strengths']=[deepcopy(lookup[i]) for i in source['strengths']]
    for p in source['tempo_evidence']:
        p['top_deviation']=deepcopy(lookup[p['top_deviation']]) if p['top_deviation'] else None
    source.update(contract=c['original_contract'],observations=observations)
    if c['scope']=='full':source.update(joints=[deepcopy(joints[k]) for k in c['full_joint_order']],phases=deepcopy(source['tempo_evidence']))
    return source
