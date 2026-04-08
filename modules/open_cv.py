from utils.video_roi_left import read_video, process_roi, unify_left_all
from utils.features_add import make_features_single_video
from utils.yolo_preprocessing import max_consecutive_none, max_consecutive_none_middle, should_discard, fill_remaining_none


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
    person_bboxes= yolo_inference(yolo_model, frames)


    # 반환된게 아무것도 없을 때 none반환: bat_angles은 bat_bboxes 퍄생이기 때문에 bat_bboxes만 체크
    if person_bboxes is None:
      print('반환되는 값이 없습니다.')
      return None

    # YOLO 결과 결측 검증 > 프레임이 5개 이상 연속으로 결측치가 있으면 영상 안씀
    if should_discard(person_bboxes, max_allowed_gap=5):
        print('person_bboxes의 결측치가 많습니다.')
        return None

    # 남은 앞, 뒤프레임 결측 채우기: fill 해서 사용
    person_bboxes = fill_remaining_none(person_bboxes)


    # --------------------------------
    # --------------------------------
    # roi 클립
    roi_frames = []
    roi_infos = []

    # roi를 통해 타자 부분만 clip + roi_info 저장
    for i in range(len(frames)):

        frame = frames[i]
        person_bbox = person_bboxes[i]

        # 구현
        roi, roi_info = process_roi(frame, person_bbox, target_size=256, pad=20)

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

    bat_positions, bat_angles = detect_bat_with_wrist(frames, wrist_landmarks, yolo_model)

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

    # 최종 피처는 [x1 y1 z1 x2 y2 z2...]... 형태로 나옴
    # 임팩트 부분을 기준으로 프레임 정렬(프레임 개수 맞추기) + 남은 피처 추가
    # 구현
    final_data = make_features_single_video(all_landmarks, bat_angles, bat_positions, dt)

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

process_all_videos(video_dir, yolo_model, save_dir, metadata_dict)


