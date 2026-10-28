"""Frozen EXP-006 display hypotheses. Numerical consistency is not pose accuracy."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import numpy as np

JOINTS = ['left_shoulder','right_shoulder','left_elbow','right_elbow','left_wrist','right_wrist',
          'left_hip','right_hip','left_knee','right_knee','left_ankle','right_ankle']
EDGES = [('shoulders',0,1),('left_upper_arm',0,2),('left_forearm',2,4),
         ('right_upper_arm',1,3),('right_forearm',3,5),('left_torso',0,6),
         ('right_torso',1,7),('pelvis',6,7),('left_thigh',6,8),('left_shin',8,10),
         ('right_thigh',7,9),('right_shin',9,11)]
LIMBS = [1,2,3,4,8,9,10,11]
REGIONS = {'torso':[0,5,6,7],'left_arm':[1,2],'right_arm':[3,4],
           'left_leg':[8,9],'right_leg':[10,11]}
IMAGE_RISKS = {'imageFiltered','imageInterpolated','imageEdgeFilled','lowImageVisibility'}
WORLD_SUPPRESS = {'missing','invalidRoot','lengthAnomaly','velocitySpike'}

@dataclass(frozen=True)
class Config:
    minimum_reference_samples:int=3
    minimum_length_ratio:float=.65
    maximum_length_ratio:float=1.35
    maximum_body_lengths_per_second:float=30.
    maximum_motion_gap_seconds:float=.12
    minimum_image_visibility:float=.5
    foot_maximum_adjacent_turn_degrees:float=90.

def finite(a):return np.isfinite(a).all(axis=-1)
def points(a):return [p.tolist() if np.isfinite(p).all() else None for p in np.asarray(a)]
def array(a):return np.array([p if p is not None else [np.nan]*3 for p in a],dtype=float)
def safe(v):
    if isinstance(v,dict):return {str(k):safe(x) for k,x in v.items()}
    if isinstance(v,(list,tuple,np.ndarray)):return [safe(x) for x in v]
    if isinstance(v,(np.bool_,bool)):return bool(v)
    if isinstance(v,(np.integer,int)):return int(v)
    if isinstance(v,(np.floating,float)):return float(v) if np.isfinite(v) else None
    return v
def stats(a):
    a=np.asarray(a,float).reshape(-1);a=a[np.isfinite(a)]
    return {'n':int(a.size),'sum':float(a.sum()),'mean':float(a.mean()) if a.size else None,
            'p95':float(np.percentile(a,95)) if a.size else None,'max':float(a.max()) if a.size else None,
            'cv':float(a.std()/a.mean()) if a.size and a.mean()>1e-12 else None}
def unit(v):
    norm=np.linalg.norm(v,axis=-1,keepdims=True)
    with np.errstate(invalid='ignore',divide='ignore'):return np.where(norm>1e-9,v/norm,np.nan)
def angles(a,b):
    ua,ub=unit(a),unit(b)
    return np.degrees(np.arccos(np.clip(np.sum(ua*ub,axis=-1),-1,1)))
def torso_available(p):
    if not finite(p[[0,1,6,7]]).all():return False
    up=(p[0]+p[1])/2-(p[6]+p[7])/2;across=p[1]-p[0];length=np.linalg.norm(up)
    return bool(length>1e-6 and np.linalg.norm(across)>1e-6 and np.linalg.norm(np.cross(across,up/length))>1e-6)
def edge_available(p):
    return np.array([bool(finite(p[[a,b]]).all() and np.linalg.norm(p[b]-p[a])>=1e-7) for _,a,b in EDGES])
def risk_dict(risks):
    names=sorted({name for row in risks for name in row})
    return {name:[j for j,row in enumerate(risks) if name in row] for name in names}

def initial_risks(world,visibility,masks,config):
    output=[]
    for i,p in enumerate(world):
        row=[set() for _ in JOINTS];valid=finite(p);root=bool(valid[[6,7]].all())
        for j in range(12):
            if not valid[j]:row[j].add('missing')
            if not root:row[j].add('invalidRoot')
            for key,name in [('combined_missing','imageFiltered'),('interpolated','imageInterpolated'),('edge_filled','imageEdgeFilled')]:
                if masks[key][i,j]:row[j].add(name)
            if np.isfinite(visibility[i,j]) and visibility[i,j]<config.minimum_image_visibility:row[j].add('lowImageVisibility')
        output.append(row)
    return output

def world_reference(world,times,fps,visibility,masks,config=Config()):
    """Per-clip unsupervised medians use the whole clip, including future frames."""
    if world.ndim!=3 or world.shape[1:]!=(12,3):raise ValueError('Expected T,12,3')
    if len(times)!=len(world) or not np.isfinite(times).all() or (np.diff(times)<=0).any():raise ValueError('Invalid time sequence')
    if not np.isfinite(fps) or fps<=0:raise ValueError('Invalid FPS')
    if config.minimum_reference_samples<1 or not 0<config.minimum_length_ratio<=config.maximum_length_ratio:raise ValueError('Invalid reference configuration')
    risks=initial_risks(world,visibility,masks,config);refs={};lengths=[];edge_bad=np.zeros((len(world),12),bool)
    for k,(name,a,b) in enumerate(EDGES):
        values=np.linalg.norm(world[:,b]-world[:,a],axis=-1);lengths.append(values)
        eligible=np.isfinite(values)&(values>1e-6)
        reference=float(np.median(values[eligible])) if eligible.sum()>=config.minimum_reference_samples else None
        refs[name]=reference
        if reference is not None:
            ratio=values/reference;edge_bad[:,k]=~np.isfinite(ratio)|(ratio<config.minimum_length_ratio)|(ratio>config.maximum_length_ratio)
        else:edge_bad[:,k]=True
        if k in LIMBS:
            for i in range(len(world)):
                if not finite(world[i,[a,b]]).all():continue
                if reference is None:risks[i][b].add('noReference')
                elif edge_bad[i,k]:risks[i][b].add('lengthAnomaly')
    torso=(world[:,0]+world[:,1])/2-(world[:,6]+world[:,7])/2
    body_lengths=np.linalg.norm(torso,axis=-1);valid=np.isfinite(body_lengths)&(body_lengths>1e-6)
    scale=float(np.median(body_lengths[valid])) if valid.any() else None
    gap=max(config.maximum_motion_gap_seconds,3/fps)
    velocity=np.zeros((len(world),12),bool)
    speeds=np.full((len(world),12),np.nan)
    if scale is not None:
        for i in range(1,len(world)):
            dt=times[i]-times[i-1]
            if dt>gap:continue
            speeds[i]=np.linalg.norm(world[i]-world[i-1],axis=-1)/dt/scale
            for j in range(12):
                # Match P0's adjacent valid eligibility except IMAGE suppression.
                if any(risks[t][j]&WORLD_SUPPRESS for t in [i-1,i]):continue
                if speeds[i,j]>config.maximum_body_lengths_per_second:
                    risks[i][j].add('velocitySpike');velocity[i,j]=True
    return dict(risks=risks,references=refs,edge_bad=edge_bad,body_scale=scale,
                speeds=speeds,velocity=velocity,direct_velocity=np.isfinite(speeds)&(speeds>config.maximum_body_lengths_per_second),
                effective_motion_gap=gap,lengths=np.asarray(lengths).T)

def package_frame(raw,shown,risks,edge_mask=None,body=None,edge_reasons=None):
    valid=finite(shown);original=finite(raw);edges=edge_available(shown)
    if edge_mask is not None:edges&=edge_mask
    torso=torso_available(shown) if body is None else bool(body and torso_available(shown))
    delta=np.linalg.norm(shown-raw,axis=-1);omitted=original&~valid;adjusted=np.isfinite(delta)&(delta>1e-6)
    imputed=~original&valid
    if imputed.any():raise AssertionError('Candidate generated a missing joint')
    automatic=np.array([bool(r-{'noReference','manualReview'}) for r in risks])
    states=['missing' if not original[j] else 'suppressed' if not valid[j] else 'uncertain' if risks[j] else 'observed' for j in range(12)]
    regions={name:bool(edges[indices].all() and (torso if name=='torso' else True)) for name,indices in REGIONS.items()}
    reasons=risk_dict(risks);warnings=[f'{key}: {len(indices)} joints' for key,indices in reasons.items()]
    if original.any() and not valid.any():warnings.insert(0,'All observed joints were suppressed by this display policy; this is not a renderer failure.')
    if valid.any() and not edges.any():warnings.insert(0,'Observed joint markers remain but no body segments are displayed.')
    return dict(positions=points(shown),joint_visible=valid.tolist(),edge_visible=edges.tolist(),torso_visible=torso,
        joint_states=states,risks=reasons,edge_reasons=edge_reasons or [[] for _ in EDGES],warnings=warnings,
        counts=dict(raw_joints=int(original.sum()),displayed_joints=int(valid.sum()),omitted_joints=int(omitted.sum()),
            adjusted_joints=int(adjusted.sum()),imputed_joints=int(imputed.sum()),visible_edges=int(edges.sum()),
            raw_available_edges=int(edge_available(raw).sum()),automatic_risk_joint_instances=int(automatic.sum()),
            automatically_flagged_visible_joint_instances=int((automatic&valid).sum()),
            delta_sum=float(np.nansum(delta)),delta_support=int(np.isfinite(delta).sum()),
            delta_max=float(np.nanmax(delta)) if np.isfinite(delta).any() else None),region_visible=regions)

def candidates(world,times,fps,visibility,masks,config=Config()):
    basis=world_reference(world,times,fps,visibility,masks,config);output=[]
    for i,raw in enumerate(world):
        risks=[set(r) for r in basis['risks'][i]];shown=raw.copy()
        for j in range(12):
            if risks[j]&WORLD_SUPPRESS:shown[j]=np.nan
        for k in LIMBS:
            name,a,b=EDGES[k]
            if not finite(shown[a]):
                if finite(shown[b]):risks[b].add('dependencyMissing')
                shown[b]=np.nan;continue
            if not finite(shown[b]):continue
            reference=basis['references'][name]
            if reference is None:continue
            direction=raw[b]-raw[a];length=np.linalg.norm(direction)
            if not np.isfinite(length) or length<=1e-6:
                risks[b].add('lengthAnomaly');shown[b]=np.nan
            else:shown[b]=shown[a]+direction*(reference/length)
        p1=package_frame(raw,shown,risks)
        p2_risks=[set(r) for r in basis['risks'][i]];edge_mask=edge_available(raw);edge_reasons=[]
        for k,(name,a,b) in enumerate(EDGES):
            reasons=[]
            if not edge_mask[k]:reasons.append('missing_or_degenerate_endpoint')
            if basis['references'][name] is None:reasons.append('no_world_reference')
            elif basis['edge_bad'][i,k]:reasons.append('world_length_deviation')
            # P2 local edge gate does not skip a numeric pair because the previous
            # observation had another warning. It never fills that missing pair.
            if basis['direct_velocity'][i,[a,b]].any():reasons.append('world_adjacent_velocity')
            if reasons:
                edge_mask[k]=False
                for j in [a,b]:
                    if finite(raw[j]):p2_risks[j].add('edgeCaution')
            edge_reasons.append(reasons)
        p2=package_frame(raw,raw.copy(),p2_risks,edge_mask=edge_mask,
            body=bool(edge_mask[[0,5,6,7]].all()),edge_reasons=edge_reasons)
        output.append({'P1':p1,'P2':p2})
    return output,basis

def baseline_frame(raw,row):
    shown=array(row['stabilized_positions']);risks=[set() for _ in JOINTS]
    for name,indices in row['risks'].items():
        for j in indices:risks[j].add(name)
    result=package_frame(raw,shown,risks)
    expected={'displayed_joints':row['stable_displayed_count'],'omitted_joints':row['additional_omitted_vs_raw_count'],
              'adjusted_joints':row['adjusted_count'],'imputed_joints':row['imputed_count']}
    for key,value in expected.items():
        if result['counts'][key]!=value:raise AssertionError('P0 count parity failed: '+key)
    result['warnings']=row['warnings']+([result['warnings'][0]] if row['raw_displayed_count'] and not row['stable_displayed_count'] else [])
    return result

def foot_candidates(world,feet,image,visibility,times,fps,config=Config()):
    """F1 is a separate optional foot experiment, never changes P0/P1/P2 body data."""
    torso=(world[:,0]+world[:,1])/2-(world[:,6]+world[:,7])/2
    existing=unit(np.cross(world[:,1]-world[:,0],torso));out=[{} for _ in world];summaries={}
    gap=max(config.maximum_motion_gap_seconds,3/fps)
    for side,heel,toe,ankle in [('left',0,2,10),('right',1,3,11)]:
        vector=feet[:,toe]-feet[:,heel];ivector=image[:,toe,:2]-image[:,heel,:2]
        lengths=np.linalg.norm(vector,axis=-1);valid=np.isfinite(lengths)&(lengths>1e-9)
        reference=float(np.median(lengths[valid])) if valid.sum()>=config.minimum_reference_samples else None
        change=np.r_[np.nan,angles(vector[1:],vector[:-1])];vis=np.minimum(visibility[:,heel],visibility[:,toe])
        worldunit=unit(vector);imageunit=unit(ivector);eligible=[];reason_counts={}
        for i in range(len(world)):
            reasons=[];anchor=bool(finite(world[i,ankle]))
            if not anchor:reasons.append('missing_ankle')
            if not valid[i]:reasons.append('missing_or_degenerate_heel_to_toe')
            if not np.isfinite(vis[i]) or vis[i]<config.minimum_image_visibility:reasons.append('low_or_missing_IMAGE_visibility_proxy')
            if reference is None:reasons.append('no_foot_length_reference')
            elif valid[i] and not config.minimum_length_ratio<=lengths[i]/reference<=config.maximum_length_ratio:reasons.append('foot_world_length_deviation')
            if i and times[i]-times[i-1]<=gap and np.isfinite(change[i]) and change[i]>config.foot_maximum_adjacent_turn_degrees:reasons.append('adjacent_direction_turn_over_90deg')
            mode='missing' if not anchor else 'simplified' if reasons else 'directional'
            for reason in reasons:reason_counts[reason]=reason_counts.get(reason,0)+1
            eligible.append(mode=='directional')
            out[i][side]=safe(dict(heel=points(feet[i,heel:heel+1])[0],toe=points(feet[i,toe:toe+1])[0],ankle=points(world[i,ankle:ankle+1])[0],
                direction_world=points(worldunit[i:i+1])[0],direction_image=points(imageunit[i:i+1])[0],
                existing_direction_world=points(existing[i:i+1])[0],mode=mode,reasons=reasons,
                image_visibility_min=vis[i],world_length=lengths[i],world_reference_length=reference,
                adjacent_direction_change_degrees=change[i],candidate_vs_existing_angle_degrees=angles(vector[i:i+1],existing[i:i+1])[0],
                note='Model-derived foot orientation candidate; IMAGE and world are separate channels, not calibrated projections; not an accuracy judgment.'))
        eligible=np.array(eligible,bool);adjacent=valid[1:]&valid[:-1]
        summaries[side]=safe(dict(frame_count=len(world),world_vector_available=int(valid.sum()),directional=int(eligible.sum()),
            simplified=sum(r[side]['mode']=='simplified' for r in out),missing=sum(r[side]['mode']=='missing' for r in out),
            raw_adjacent_support=int(adjacent.sum()),raw_adjacent_turn_over_90=int((change[1:][adjacent]>90).sum()),
            eligible_adjacent_support=int((eligible[1:]&eligible[:-1]).sum()),
            reason_counts=reason_counts,world_length=stats(lengths),candidate_vs_existing_angle=stats(angles(vector,existing)),
            adjacent_change=stats(change),image_visibility_min=stats(vis)))
    return out,summaries

FROZEN_CONFIG=asdict(Config())
