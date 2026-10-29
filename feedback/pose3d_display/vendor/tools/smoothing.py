"""Frozen S1/S2 display-coordinate candidates; no inference or missing imputation.

S1 uses the One Euro adaptive low-pass formulation with a shared 3D-vector
cutoff, so reflecting or rotating a clip does not change filter strength.
S2 fits local quadratics on actual timestamps, rather than passing irregular
timestamps to an evenly-spaced Savitzky-Golay implementation. This is an offline
robust local-polynomial candidate, not a claim of recovered ground truth.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'config/smoothing.json').read_text('utf-8'))
EDGES = [(0,1),(0,2),(2,4),(1,3),(3,5),(0,6),(1,7),(6,7),
         (6,8),(8,10),(7,9),(9,11)]
BODY_NAMES = ['left_shoulder','right_shoulder','left_elbow','right_elbow',
              'left_wrist','right_wrist','left_hip','right_hip','left_knee',
              'right_knee','left_ankle','right_ankle']
EPS = 1e-12


def adapt_timestamps(clip):
    """Time-only adapter shared by S0/S1/S2; original coordinates are unchanged."""
    result=copy.deepcopy(clip)
    pts=np.array([f.get('decoded_pts_s') for f in result['frames']],float)
    nominal=np.array([f['timestamp_s'] for f in result['frames']],float)
    if not np.isfinite(pts).all() or np.any(np.diff(pts)<=0):
        raise ValueError('Finite strictly increasing decoded PTS required')
    times=pts-pts[0]
    for i,frame in enumerate(result['frames']):
        frame['npz_timestamp_s']=frame['timestamp_s'];frame['timestamp_s']=float(times[i])
    result['temporal_adapter']={'source':'decoded_pts_s','origin_s':float(pts[0]),
       'nominal_fps_metadata_unchanged':result['fps'],'max_npz_pts_difference_s':float(np.max(np.abs(times-nominal))),
       'median_decoded_dt_s':float(np.median(np.diff(times))) if len(times)>1 else None,
       'actual_interval_min_s':float(np.min(np.diff(times))) if len(times)>1 else None,
       'actual_interval_max_s':float(np.max(np.diff(times))) if len(times)>1 else None,
       'S0_coordinate_change':False,'note':'Shared time correction; S0 is not byte-identical in timestamps to prior nominal-time playback'}
    result['smoothing']={'version':CONFIG['version'],'condition':'S0','joint_coordinates_modified':False,
                         'raw_missingness_preserved':True,'original_p2_masks_preserved':True,'actual_accuracy':'not_measured'}
    return result


def as_points(value, count):
    if value is None:
        return np.full((count, 3), np.nan)
    if len(value) != count:
        raise ValueError('Point count mismatch')
    result = np.full((count, 3), np.nan)
    for j, point in enumerate(value):
        if point is not None:
            point = np.asarray(point, dtype=float)
            if point.shape != (3,) or not np.isfinite(point).all():
                raise ValueError('Malformed coordinate; use explicit null for missing')
            result[j] = point
    return result


def clip_arrays(clip):
    if clip.get('coordinate_convention') != CONFIG['coordinate_contract'] or clip.get('source_oriented') is not True:
        raise ValueError('Explicit restored coordinate convention required')
    if clip['joint_names'] != BODY_NAMES:
        raise ValueError('Unexpected joint order')
    frames = clip['frames']
    times = np.array([f['timestamp_s'] for f in frames], dtype=float)
    if not len(times) or not np.isfinite(times).all() or times[0] != 0 or np.any(np.diff(times) <= 0):
        raise ValueError('Timestamps must start at zero and strictly increase')
    if clip.get('frame_count', len(frames)) != len(frames):
        raise ValueError('Frame count mismatch')
    for i, frame in enumerate(frames):
        if frame.get('index', i) != i:
            raise ValueError('Frame index mismatch')
    body = np.array([as_points(f['positions'],12) for f in frames])
    feet = np.array([as_points(f.get('feet'),4) for f in frames])
    return times, body, feet


def gap_limit(times):
    median_dt = float(np.median(np.diff(times))) if len(times)>1 else 0.
    return max(CONFIG['gap']['absolute_s'], CONFIG['gap']['median_dt_multiplier']*median_dt)


def segments(points, times, max_gap):
    valid = np.isfinite(points).all(axis=-1)
    previous = np.vstack([np.zeros((1, valid.shape[1]),bool),valid[:-1]])
    breaks = np.r_[True,np.diff(times)>max_gap]
    starts = valid & (~previous | breaks[:,None])
    labels = np.cumsum(starts,axis=0)
    return np.where(valid,labels,-1)


def original_masks(clip):
    visible = np.array([f.get('p2',{}).get('edge_visible',[False]*12) for f in clip['frames']],bool)
    warnings = np.array([f.get('p2',{}).get('joint_warnings',[True]*12) for f in clip['frames']],bool)
    if visible.shape != (len(clip['frames']),12) or warnings.shape != visible.shape:
        raise ValueError('Malformed P2 masks')
    return visible,warnings


def scale_and_references(body, clip):
    visible,warnings = original_masks(clip)
    refs = np.full(12,np.nan)
    eligible_counts=[];fallback=[]
    for e,(a,b) in enumerate(EDGES):
        lengths=np.linalg.norm(body[:,b]-body[:,a],axis=-1)
        finite=np.isfinite(lengths)&(lengths>EPS)
        good=finite & visible[:,e] & ~warnings[:,a] & ~warnings[:,b]
        eligible_counts.append(int(good.sum()))
        values=lengths[good]
        if len(values)<CONFIG['S2']['minimum_reference_observations']:
            values=lengths[finite];fallback.append(e)
        if len(values):refs[e]=np.median(values)
    parts=[refs[[5,6]],refs[[8,10]],refs[[9,11]]]
    scale=float(sum(np.mean(p[np.isfinite(p)]) for p in parts)) if all(np.isfinite(p).any() for p in parts) else 1.
    if not np.isfinite(scale) or scale<=EPS:scale=1.
    return scale,refs,{'reference_eligible_counts':eligible_counts,'reference_fallback_edges':fallback,
                      'body_scale_fallback':not all(np.isfinite(p).any() for p in parts)}


def one_euro(points, times, scale, max_gap, config=None):
    cfg=config or CONFIG['S1']
    out=np.full_like(points,np.nan)
    previous_raw=np.full(points.shape[1:],np.nan)
    previous_filtered=np.full_like(previous_raw,np.nan)
    derivative=np.zeros_like(previous_raw)
    previous_valid=np.zeros(points.shape[1],bool)
    resets=0
    for i,t in enumerate(times):
        current=points[i];valid=np.isfinite(current).all(axis=-1)
        dt=float(t-times[i-1]) if i else 0.
        continuing=valid & previous_valid & (dt<=max_gap) & (dt>0)
        fresh=valid & ~continuing
        out[i,fresh]=current[fresh];derivative[fresh]=0.
        resets += int(fresh.sum())
        if continuing.any():
            raw_d=(current[continuing]-previous_raw[continuing])/dt
            ad=1./(1.+1./(2.*np.pi*cfg['derivative_cutoff_hz']*dt))
            derivative[continuing]=ad*raw_d+(1-ad)*derivative[continuing]
            cutoff=cfg['min_cutoff_hz']+cfg['beta']*np.linalg.norm(derivative[continuing],axis=-1)/scale
            alpha=1./(1.+1./(2.*np.pi*cutoff*dt))
            out[i,continuing]=alpha[:,None]*current[continuing]+(1-alpha[:,None])*previous_filtered[continuing]
        previous_raw=current.copy();previous_filtered=out[i].copy();previous_valid=valid
    return out,{'segment_resets':resets}


def adjacent_speed(points, times, max_gap):
    if len(times)<2:return np.empty((0,points.shape[1]))
    dt=np.diff(times)
    speed=np.linalg.norm(np.diff(points,axis=0),axis=-1)/dt[:,None]
    speed[dt>max_gap]=np.nan
    return speed


def robust_local_polynomial(points,times,scale,max_gap,config=None):
    cfg=config or CONFIG['S2'];out=points.copy();labels=segments(points,times,max_gap)
    speeds=adjacent_speed(points,times,max_gap)/scale
    v=np.zeros(points.shape[:2])
    if len(times)>1:
        finite=np.nan_to_num(speeds,nan=0.)
        v[:-1]=finite;v[1:]=np.maximum(v[1:],finite)
    fractions=1./(1.+(v/cfg['speed_blend_scale_per_s'])**2)
    fit_count=0;insufficient=0;downweighted=0;weighted_total=0
    for i,t in enumerate(times):
        ix=np.flatnonzero(np.abs(times-t)<=cfg['half_window_s']+EPS)
        valid=(labels[ix]==labels[i]) & (labels[i]>=0)[None,:]
        active=np.flatnonzero(valid.sum(axis=0)>=cfg['minimum_samples'])
        insufficient+=int(np.isfinite(points[i]).all(axis=-1).sum()-len(active))
        if not len(active):continue
        x=(times[ix]-t)/cfg['half_window_s']
        design=np.stack([x**k for k in range(cfg['polynomial_degree']+1)],axis=1)
        y=np.nan_to_num(points[ix][:,active],nan=0.)
        allowed=valid[:,active];weights=allowed.astype(float)
        for iteration in range(cfg['huber_iterations']+1):
            normal=np.einsum('wi,wj,wk->kij',design,design,weights)
            rhs=np.einsum('wi,wkj,wk->kij',design,y,weights)
            coefficients=np.linalg.solve(normal,rhs)
            if iteration==cfg['huber_iterations']:break
            residual=np.linalg.norm(y-np.einsum('wi,kij->wkj',design,coefficients),axis=-1)
            robust_scale=1.4826*np.nanmedian(np.where(allowed,residual,np.nan),axis=0)
            robust_scale=np.maximum(robust_scale,cfg['robust_scale_floor_fraction']*scale)
            huber=np.minimum(1.,cfg['huber_c']*robust_scale[None,:]/np.maximum(residual,EPS))
            weights=allowed*huber
        downweighted+=int(np.sum(allowed&(weights<.999999)))
        weighted_total+=int(allowed.sum())
        fraction=fractions[i,active,None]
        out[i,active]=fraction*coefficients[:,0,:]+(1-fraction)*points[i,active]
        fit_count+=len(active)
    return out,{'local_fits':fit_count,'insufficient_samples_kept_raw':insufficient,
                'huber_downweighted_window_samples':downweighted,'window_samples':weighted_total,
                'smooth_fraction_min':float(np.min(fractions)),'smooth_fraction_mean':float(np.mean(fractions))}


def length_constraints(body,feet,clip,scale,references,reference_counts):
    cfg=CONFIG['S2'];out=body.copy();extra=feet.copy();visible,warnings=original_masks(clip)
    corrected=0;capped=0;severe_skipped=0;policy_skipped=0;missing_reference=0
    max_change=0.
    for i in range(len(body)):
        for e in cfg['constrained_edges']:
            a,b=EDGES[e]
            if not visible[i,e] or warnings[i,a] or warnings[i,b]:policy_skipped+=1;continue
            if reference_counts[e]<cfg['minimum_reference_observations'] or not np.isfinite(references[e]):missing_reference+=1;continue
            delta=out[i,b]-out[i,a];length=float(np.linalg.norm(delta))
            if not np.isfinite(length) or length<=EPS:continue
            ratio=length/references[e]
            if not cfg['length_ratio_min']<=ratio<=cfg['length_ratio_max']:severe_skipped+=1;continue
            requested=cfg['length_correction_fraction']*(references[e]-length)
            cap=cfg['length_correction_cap_scale_fraction']*scale
            applied=float(np.clip(requested,-cap,cap));shift=applied*delta/length
            if abs(requested)>cap:capped+=1
            if abs(applied)>EPS:
                corrected+=1;out[i,b]+=shift;max_change=max(max_change,abs(applied))
                if b in (10,11):
                    indexes=[0,2] if b==10 else [1,3]
                    for f in indexes:
                        if np.isfinite(extra[i,f]).all():extra[i,f]+=shift
    return out,extra,{'corrected_edges':corrected,'cap_hits':capped,'severe_ratio_skipped':severe_skipped,
                      'original_policy_skipped':policy_skipped,'insufficient_reference_skipped':missing_reference,
                      'max_applied_child_shift':max_change,'max_applied_child_shift_normalized':max_change/scale}


def recenter(body,feet):
    root=(body[:,6]+body[:,7])*.5
    valid=np.isfinite(root).all(axis=-1)
    body[valid]-=root[valid,None,:];feet[valid]-=root[valid,None,:]
    return body,feet


def json_points(points):
    return [p.tolist() if np.isfinite(p).all() else None for p in points]


def smooth_clip(clip,mode):
    if mode not in ('S1','S2'):raise ValueError('S0 is the unchanged upstream clip')
    times,body,feet=clip_arrays(clip);scale,refs,refmeta=scale_and_references(body,clip)
    limit=gap_limit(times);allpoints=np.concatenate([body,feet],axis=1)
    fn=one_euro if mode=='S1' else robust_local_polynomial
    filtered,diag=fn(allpoints,times,scale,limit)
    newbody,newfeet=filtered[:,:12],filtered[:,12:]
    constraints={}
    if mode=='S2':newbody,newfeet,constraints=length_constraints(newbody,newfeet,clip,scale,refs,refmeta['reference_eligible_counts'])
    newbody,newfeet=recenter(newbody,newfeet)
    if not np.array_equal(np.isfinite(body).all(-1),np.isfinite(newbody).all(-1)) or not np.array_equal(np.isfinite(feet).all(-1),np.isfinite(newfeet).all(-1)):
        raise AssertionError('Smoothing altered missingness')
    result=copy.deepcopy(clip)
    for i,frame in enumerate(result['frames']):
        frame['positions']=json_points(newbody[i])
        if 'feet' in frame:frame['feet']=json_points(newfeet[i])
    result['smoothing']={'version':CONFIG['version'],'condition':mode,'body_scale':scale,'effective_gap_s':limit,
                         'raw_missingness_preserved':True,'original_p2_masks_preserved':True,
                         'actual_accuracy':'not_measured','offline_reference_scale':True,
                         'joint_coordinates_modified':True,'diagnostics':diag,'length_constraints':constraints,**refmeta}
    return result
