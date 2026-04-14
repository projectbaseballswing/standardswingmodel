import cv2
from modules.utils.video_roi_left import read_video, process_roi, unify_left_all, normalize_landmarks_sequence
from modules.utils.features_add import make_features_single_video
from modules.utils.yolo_preprocessing import max_consecutive_none, max_consecutive_none_middle, should_discard, fill_remaining_none
from modules.yolo_obb_tracker import track_target_player_and_bat
from modules.preprocessing import preprocess_player, preprocess_bat
from modules.extract_pose_with_roi import extract_pose_with_roi

def get_video_size(video_path):
    cap = cv2.VideoCapture(video_path)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    
    return (width, height)

# video_path: 비디오 한 개의 경로, yolo_model: 욜로 모델, metadata: 좌우유무 파일
def process_video(video_path, yolo_model, is_left=False):
    # 비디오 > 프레임 리스트로 바꿈 + fps 같이 반환
    frames, fps = read_video(video_path)
    dt = 1 / fps
    # 프레임 height, width
    H, W = frames[0].shape[:2]

    # 사람 좌표만 먼저 추출
    # --------------------------------
    # --------------------------------
    # !! yolo_inference 이 부분 구현 !! > 바뀐 부분
    extracted_data = track_target_player_and_bat(yolo_model, frames)

    # 반환된게 아무것도 없을 때 none반환: bat_angles은 bat_bboxes 퍄생이기 때문에 bat_bboxes만 체크
    if extracted_data["player"] is None:
        print("Target Not Found")
        return None, None
    
    # Player 전처리
    # 결측치 보정 -> 이상치 보정 -> 뒤틀림 및 영역 벗어남 보정 -> df to np
    player_df = extracted_data["player"]
    player_np, is_max_gap_exceeded = preprocess_player(player_df, W, H)
    
    # Bat 전처리
    # 각도 언래핑(0~90도를 연속값으로 보정) -> 결측치 보정 -> 이상치 보정 -> df to np
    bat_df = extracted_data["bat"]
    bat_np = preprocess_bat(bat_df)

    '''
    [ 여기까지 진행했을 때 변수 목록 ]
    player_np : player xyxy 데이터 (numpy) [xmin, ymin, xmax, ymax]
    is_max_gap_exceeded : player의 결측 프레임이 연속 5 이상인지 여부 (boolean)
    bat_np : bat xywhr 데이터 (numpy) [cx, cy, w, h, r]
    '''

    # YOLO 결과 결측 검증 > 프레임이 5개 이상 연속으로 결측치가 있으면 영상 안씀
    if is_max_gap_exceeded:
        print('person_bboxes의 결측치가 많습니다.')
        return None, None


    # --------------------------------
    # --------------------------------
    # roi 클립
    roi_frames = []
    roi_infos = []

    # roi를 통해 타자 부분만 clip + roi_info 저장
    for i in range(len(frames)):

        frame = frames[i]
        person_bbox = player_np[i]

        # 구현
        roi, roi_info = process_roi(frame, player_np[i], target_size=256, pad=20)

        roi_frames.append(roi)
        roi_infos.append(roi_info)

    # --------------------------------
    # --------------------------------
    # 원본 좌표로 복원한 후 정규화 진행
    # all_landmarks: [x,y,z,1], [x,y,z,1], [x,z,y,0]... 형태로 나옴
    # wrist_landmarks는 원본 좌표만 (정규환 안된거)
    # roi_infos = [ {frame1 정보}, {frame2 정보}, {frame3 정보}, ...]
    all_landmarks, wrist_landmarks = extract_pose_with_roi(roi_frames,roi_infos,fps)

    if all_landmarks is None:
        print('landmarks 없음')
        return None

    # --------------------------------
    # --------------------------------
    # bat 정보 추출
    bat_positions = []
    bat_angles = []

    # visibility 추가로 받음: 넘파이 형태 
    bat_positions, bat_angles, visibility  = detect_bat_with_wrist(frames, wrist_landmarks, yolo_model)

    if should_discard(bat_positions, max_allowed_gap=5):
        print('bat 검출 실패 많음')
        return None

    bat_positions = fill_remaining_none(bat_positions)
    bat_angles = fill_remaining_none(bat_angles)

    # 좌우 통일 / W: width
    if is_left:
        all_landmarks, bat_positions, bat_angles = unify_left_all(
            all_landmarks,
            bat_positions,
            bat_angles,
            W
        )
        
    # 정규화 코드 추가 
    all_landmarks_final = normalize_landmarks_sequence(all_landmarks, visibility)

    # 최종 피처는 [x1 y1 z1 x2 y2 z2...]... 형태로 나옴
    # 임팩트 부분을 기준으로 프레임 정렬(프레임 개수 맞추기) + 남은 피처 추가
    # 구현
    final_data = make_features_single_video(all_landmarks_final, bat_angles, bat_positions, dt)

    return final_data


#---------------------------------------------------------
#---------------------------------------------------------
#---------------------------------------------------------
# 영상 전체 함수
'''
T1 = 프레임 개수 / F = 피처 개수
results = { 
    "video1.mp4": np.array(T1, F), 
    "video2.mp4": np.array(T2, F), 
    "video3.mp4": np.array(T3, F), 
}
'''

# video_dir: 영상들이 들어있는 폴더 경로 / yolo_model: YOLO 모델 /
import os
import gc

def process_all_videos(video_dir, yolo_model, save_dir, metadata_dict=None):


    for file_name in os.listdir(video_dir):

        # 1. 영상 파일만 필터링
        if not file_name.lower().endswith(('.mp4', '.avi', '.mov')):
            continue

        video_path = os.path.join(video_dir, file_name)
        
        # 2. 좌우 판단
        if metadata_dict is not None:
            # 해당 영상의 메타데이터 가져오기 / 없으면 빈 dict {}
            meta = metadata_dict.get(file_name, {})
            # "handness" 값 가져오기 / "handness" 값 가져오기
            handness = meta.get("handness", "right")
            # left면 True, 아니면 False
            is_left = (handness == "left")
        else:
            is_left = False
            
        # 영상 처리 + 에러방지 포함
        try:
            output = process_video(
                video_path,
                yolo_model,
                is_left=is_left
            )
        except Exception as e:
            print(f"[ERROR] {file_name}:", e)
            continue
        
        # return 결과가 None이면 넘어감
        if output is None:
            print(f"[SKIP] {file_name}")
            continue
        
       # 파일로 저장: 메모리 터지는거 방지
        save_path = os.path.join(
            save_dir,
            file_name.replace(".mp4", ".npy")
                     .replace(".avi", ".npy")
                     .replace(".mov", ".npy")
        )

        np.save(save_path, output)
            
        # 5. 메모리 해제: 메모리 터지는거 방지
        # 영상 하나 처리 결과 메모리에서 제거
        del output
        # 파이썬이 바로 안 지우는 메모리까지 강제 정리
        gc.collect()
        
        print(f"[OK] {file_name} 저장 완료")

    print("전체 처리 완료")


#---------------------------------------------------------
#---------------------------------------------------------
#---------------------------------------------------------

import os
import gc
import numpy as np
import cv2

# 실행 함수
video_dir = "videos"
yolo_model = ""
save_dir = 'output_numpy'
metadata_dict = "metadata.json"

# process_all_videos(video_dir, yolo_model, save_dir, metadata_dict)

