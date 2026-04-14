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

def track_target_player_and_bat(model, frames, player_cls=2, bat_cls=0):
    '''
    영상에서 각 타자와 배트를 추적하고 
    가중치로 평가해 점수가 가장 높은 객체를 타겟으로 설정한다.
    
    [parameter]
      model : custom-yolo-obb-model
      frames : 분석하고자 하는 영상의 프레임 목록
      player_cls : model에 학습되어있는 player class
      bat_cls : model에 학습되어있는 bat class
    
    [return]
      { "player": 타겟 타자의 좌표 추적 값(pd.dataFrame),
        "bat" : 타겟 배트의 좌표 추적 값(pd.dataFrame)}
    '''
    
    print("타겟 Player와 Bat를 추적합니다")
    
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
        
    target_player_id = max(score_board, key=score_board.get)
    target_bat_id = player_associated_bats.get(target_player_id, None)
    
    print(f"    타겟 Player ID: {target_player_id} / Bat ID: {target_bat_id}")

    # Player와 Bat 좌표 데이터 병합 및 딕셔너리 반환
    print("[3] 타겟 Player & Bat 데이터 정리")
    
    # 1. 뼈대 생성 (1 ~ 전체 프레임)
    base_df = pd.DataFrame({'frame': range(1, frame_idx + 1)})
    
    # 2. Player 데이터 완성
    target_p_df = df_players[df_players['track_id'] == target_player_id][['frame', 'coords']]
    merged_p_df = pd.merge(base_df, target_p_df, on='frame', how='left')
    
    p_coords_list = [c if isinstance(c, list) else [np.nan] * 4 for c in merged_p_df['coords']]
    p_cols = ['xmin', 'ymin', 'xmax', 'ymax'] 
    final_player_df = pd.concat([base_df, pd.DataFrame(p_coords_list, columns=p_cols)], axis=1)
    
    # 3. Bat 데이터 완성
    if target_bat_id is not None:
        target_b_df = df_bats[df_bats['track_id'] == target_bat_id][['frame', 'coords']]
        merged_b_df = pd.merge(base_df, target_b_df, on='frame', how='left')
        b_coords_list = [c if isinstance(c, list) else [np.nan] * 5 for c in merged_b_df['coords']]
        b_cols = ['cx', 'cy', 'w', 'h', 'r']
        final_bat_df = pd.concat([base_df, pd.DataFrame(b_coords_list, columns=b_cols)], axis=1)
    else:
        print("경고: 타겟 배트가 감지되지 않았습니다.")
        final_bat_df = None
        
    print("모든 처리 완료")
    
    # 4. 딕셔너리로 묶어서 반환
    return {
        "player": final_player_df,
        "bat": final_bat_df
    }
