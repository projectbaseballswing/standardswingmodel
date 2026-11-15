import bisect

import cv2
import numpy as np
import pandas as pd
from ultralytics import YOLO

# 두 좌표의 거리 계산
def _calculate_distance(pt1, pt2):
    return np.sqrt((pt1[0] - pt2[0])**2 + (pt1[1] - pt2[1])**2)

# Target Player 선정을 위한 가중치 계산
def _score_weight(p_area, min_bat_dist, center_dist, 
                 area_weight=0.5, bat_dist_weight=2.0, center_dist_weight=1.0):
    '''
    target player 선정을 위한 가중치 계산
    1. area : bounding box의 크기가 큰 객체
    2. bat dist : bat와 가까이 있는 객체
    3. center dist : 화면 중앙부에 위치한 객체
    '''
    return (p_area * area_weight) - (min_bat_dist * bat_dist_weight) - (center_dist * center_dist_weight)

# 트랙 복원 임계값
STITCH_MAX_SEAM_GAP = 5          # 인접 트랙 경계의 최대 끊김(프레임)
STITCH_CENTER_RATIO = 0.6        # 중심 이동 허용치 = 박스폭 × 이 비율
STITCH_AREA_RATIO = 2.0          # 경계 면적비 허용 상한(역수에도 적용)
STITCH_OVERLAP_MIN_FRAMES = 2    # 겹침 판정에 필요한 최소 공통 프레임 수


def _box_w(row):
    c = row['coords']
    return abs(c[2] - c[0]) if isinstance(c, (list, tuple)) and len(c) >= 4 else None


def _same_person(a_rows, b_rows):
    '''
    두 player 트랙(track_id)이 '같은 사람'인지 공간 정보로 판정한다.

    - 시간이 겹치는 경우(유령 중복 트랙 가능): 겹치는 프레임에서 두 박스가
      공간적으로 거의 같은 위치면(중심거리 중앙값이 박스폭 대비 작음) 같은 사람,
      멀면 다른 사람(예: 투수·포수)으로 본다.
    - 시간이 안 겹치고 인접한 경우: 가장 가까운 프레임 쌍의 경계에서
      중심 이동이 작고(박스폭 비례) 면적비가 비슷하면 같은 사람으로 본다.
    '''
    shared = set(a_rows) & set(b_rows)
    if len(shared) >= STITCH_OVERLAP_MIN_FRAMES:
        dists, widths = [], []
        for f in shared:
            ar, br = a_rows[f], b_rows[f]
            dists.append(((ar['cx'] - br['cx']) ** 2 + (ar['cy'] - br['cy']) ** 2) ** 0.5)
            bw = _box_w(ar) or _box_w(br)
            if bw:
                widths.append(bw)
        if not widths:
            return False
        return float(np.median(dists)) <= STITCH_CENTER_RATIO * float(np.median(widths))
    if shared:
        return False  # 겹치긴 하는데 표본이 너무 적으면 보수적으로 병합 안 함

    # 인접 경계: 두 트랙에서 가장 가까운 프레임 쌍을 찾는다(감싸는 구조도 처리)
    a_sorted = sorted(a_rows)
    seam = None  # (gap, a_frame, b_frame)
    for bf in b_rows:
        pos = bisect.bisect_left(a_sorted, bf)
        for j in (pos - 1, pos):
            if 0 <= j < len(a_sorted):
                af = a_sorted[j]
                g = abs(af - bf)
                if seam is None or g < seam[0]:
                    seam = (g, af, bf)
    if seam is None:
        return False
    gap, af, bf = seam
    if gap > STITCH_MAX_SEAM_GAP:
        return False
    ar, br = a_rows[af], b_rows[bf]
    dist = ((ar['cx'] - br['cx']) ** 2 + (ar['cy'] - br['cy']) ** 2) ** 0.5
    bw = _box_w(ar) or _box_w(br)
    if bw is None or dist > STITCH_CENTER_RATIO * bw:
        return False
    a1, a2 = ar['area'], br['area']
    if a1 <= 0 or a2 <= 0 or max(a1 / a2, a2 / a1) > STITCH_AREA_RATIO:
        return False
    return True


def _reconstruct_person(rows_by_id, anchor_id):
    '''
    배트 근접 점수로 '타자'를 식별한 anchor_id 를 기준으로, 같은 사람의 조각난/중복된
    track_id 들을 모아 한 사람으로 복원한다. 겹치는 트랙(유령 중복)과 인접 트랙 모두
    _same_person 판정으로만 묶으므로, 다른 사람(투수·포수 등)은 끼지 않는다.

    [return] 같은 사람으로 묶인 track_id 들을 '커버리지 내림차순'으로 정렬한 리스트.
             앞쪽(가장 긴 트랙)을 우선으로 프레임을 채우기 위함.
    '''
    person = {anchor_id}
    changed = True
    while changed:
        changed = False
        for tid, rows in rows_by_id.items():
            if tid in person:
                continue
            if any(_same_person(rows_by_id[p], rows) for p in person):
                person.add(tid)
                changed = True
    ordered = sorted(person, key=lambda t: -len(rows_by_id[t]))
    if len(ordered) > 1:
        print(f"트랙 복원: anchor={anchor_id} + {[t for t in ordered if t != anchor_id]} "
              f"→ {len(ordered)}개 트랙을 한 사람으로 병합")
    return ordered


def track_target_player(model, frames, player_cls=2, bat_cls=0):
    '''
    영상에서 각 타자와 배트를 추적하고 
    가중치로 평가해 점수가 가장 높은 객체를 타겟으로 설정한다.
    
    [parameter]
      model : custom-yolo-obb-model
      frames : 분석하고자 하는 영상의 프레임 목록
      player_cls : model에 학습되어있는 player class
      bat_cls : model에 학습되어있는 bat class
    
    [return]
      타겟 타자의 좌표 추적 값(pd.dataFrame)
    '''
    
    print("타겟 Player를 추적합니다")
    
    # 전체 영상 객체 추적 및 데이터 수집
    print("[1] 전체 영상 객체 추적 및 데이터 수집 시작")
    # cap = cv2.VideoCapture(video_path)
    
    height, width, _ = frames[0].shape
    image_center = (width / 2, height / 2)
    
    tracking_data = []
    frame_idx = 0
    frames_length = len(frames)
    
    # 새 영상 분석 시작 전에 이전 추적 기록을 명시적으로 초기화
    if hasattr(model, 'predictor') and model.predictor is not None and hasattr(model.predictor, 'trackers'):
        for tracker in model.predictor.trackers:
            tracker.reset()
        
    while frame_idx < frames_length:
        frame = frames[frame_idx]
            
        results = model.track(frame, conf=0.01, persist=True, imgsz=1280, verbose=False)
        result = results[0]
        
        if result.obb is not None and result.obb.id is not None:
            for i in range(len(result.obb)):
                cls_id = int(result.obb.cls[i].item())
                track_id = int(result.obb.id[i].item())
                
                cx, cy, w, h, _ = result.obb.xywhr[i].cpu().numpy()
                # Player는 xyxy(4개) Bat은 xywhr(5개) 좌표
                if cls_id == player_cls:
                    # Player: ROI를 위해 수평/수직을 유지하는 외곽 박스 좌표 사용 (xmin, ymin, xmax, ymax)
                    coords = result.obb.xyxy[i].cpu().numpy().flatten().tolist()
                elif cls_id == bat_cls:
                    # Bat: 기울기 확인을 위해 각도가 포함된 좌표 사용 (centerx, centery, width, height, radian)
                    coords = result.obb.xywhr[i].cpu().numpy().flatten().tolist()
                else:
                    continue
                
                tracking_data.append({
                    'frame': frame_idx,
                    'track_id': track_id,
                    'class_id': cls_id,
                    'cx': cx, 'cy': cy, 'area': w * h,
                    'coords': coords
                })
        frame_idx += 1
    
    df = pd.DataFrame(tracking_data)
    if df.empty:
        return None

    # 글로벌 스코어링 및 타겟 확정 
    print("[2] 글로벌 스코어링 진행")
    df_players = df[df['class_id'] == player_cls]
    df_bats = df[df['class_id'] == bat_cls]
    
    if df_players.empty: 
        print("Player Not Found")
        return None
    
    score_board = {}
    player_associated_bats = {} 
    
    # Target Player, Bat를 찾기 위한 Scoring
    for player_id, p_group in df_players.groupby('track_id'):
        total_score = 0
        bat_id_counts = {} 
        
        for _, p_row in p_group.iterrows():
            f_idx = p_row['frame']
            p_cx, p_cy, p_area = p_row['cx'], p_row['cy'], p_row['area']
            
            b_in_frame = df_bats[df_bats['frame'] == f_idx]
            min_bat_dist = width
            closest_bat_id = None
            
            if not b_in_frame.empty:
                for _, b_row in b_in_frame.iterrows():
                    dist = _calculate_distance((p_cx, p_cy), (b_row['cx'], b_row['cy']))
                    if dist < min_bat_dist:
                        min_bat_dist = dist
                        closest_bat_id = b_row['track_id'] 
            
            if closest_bat_id is not None:
                bat_id_counts[closest_bat_id] = bat_id_counts.get(closest_bat_id, 0) + 1
            
            center_dist = _calculate_distance((p_cx, p_cy), image_center)
            frame_score = _score_weight(p_area, min_bat_dist, center_dist)
            total_score += frame_score
            
        score_board[player_id] = total_score / len(p_group)
        if bat_id_counts:
            player_associated_bats[player_id] = max(bat_id_counts, key=bat_id_counts.get)
        
    # 배트 근접 점수로 '타자(사람)'를 식별한다. 이 선정 자체는 신뢰할 수 있지만,
    # 트래커가 ID를 갈아타거나 유령 중복 트랙을 만들면 이 anchor 트랙이 일부 구간
    # (예: 컨택 순간)만 남는다. 아래에서 같은 사람의 트랙 전체를 복원한다.
    anchor_player_id = max(score_board, key=score_board.get)
    # target_bat_id = player_associated_bats.get(anchor_player_id, None)

    # --- 타자 트랙 복원: anchor 와 같은 사람인 track_id 들을 모아 스윙 전체를 복원 ---
    # 겹치는 트랙(유령 중복)은 공간 근접으로, 인접 트랙은 경계 연속성으로 판정해
    # '같은 사람'일 때만 병합한다(투수·포수 등 다른 사람은 공간적으로 멀어 제외됨).
    rows_by_id = {
        tid: {int(r['frame']): r for _, r in g.iterrows()}
        for tid, g in df_players.groupby('track_id')
    }
    person_ids = _reconstruct_person(rows_by_id, anchor_player_id)

    # Player와 Bat 좌표 데이터 병합 및 딕셔너리 반환
    print("[3] 타겟 Player & Bat 데이터 정리")

    # 1. 뼈대 생성 (1 ~ 전체 프레임)
    base_df = pd.DataFrame({'frame': range(1, frame_idx + 1)})

    # 2. Player 데이터 완성
    #    같은 사람으로 묶인 트랙들을 '커버리지 우선'으로 프레임마다 하나씩 채운다.
    #    (가장 긴 트랙을 기본으로, 그 트랙이 비는 프레임만 다른 트랙으로 보충)
    chosen = {}  # frame -> coords
    for tid in person_ids:
        for f, r in rows_by_id[tid].items():
            if f not in chosen:
                chosen[f] = r['coords']
    target_p_df = pd.DataFrame(
        [{'frame': f, 'coords': chosen[f]} for f in sorted(chosen)]
    )
    merged_p_df = pd.merge(base_df, target_p_df, on='frame', how='left')
    
    p_coords_list = [c if isinstance(c, list) else [np.nan] * 4 for c in merged_p_df['coords']]
    p_cols = ['xmin', 'ymin', 'xmax', 'ymax'] 
    final_player_df = pd.concat([base_df, pd.DataFrame(p_coords_list, columns=p_cols)], axis=1)
        
    print("모든 처리 완료")
    
    # 3. 반환
    return final_player_df
