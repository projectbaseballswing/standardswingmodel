import cv2
import numpy as np

# read_video / process_roi / unify_left_all

################################################################
################################################################
################################################################

# 영상 읽기
def read_video(video_path):
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        raise ValueError(f"영상 열기 실패: {video_path}")

    # fps 가져오기
    fps = cap.get(cv2.CAP_PROP_FPS)
    
    # fps가 0이 나온는 경우 기본값 30으로 설정 
    if fps == 0:
        fps = 30

    frames = []

    while True:
        # 읽을 프레임이 없을 때까지 반복
        ret, frame = cap.read()
        # 더 이상 읽을 프레임 없으면 종료
        if not ret:
            break

        frames.append(frame)

    cap.release()

    return frames, fps


################################################################
################################################################
################################################################

# roi 클립 
# frame: 원본 이미지 (H, W, C) / bbox: (x1, y1, x2, y2) / target_size: 출력 크기 (정사각형) / pad: bbox 주변 padding
def process_roi(frame, bbox, target_size=256, pad=20):

    # 이미지 높이(h), 너비(w)
    h, w, _ = frame.shape

    #############################################
    # bbox좌표: yolo가 어떤걸주느냐에 따라 바뀔 부분
    x1, y1, x2, y2 = bbox

    # 1. bbox에 padding 추가
    # 사람 주변 여유 공간 확보: 팔/배트 잘리는 문제 방지
    x1 = int(x1 - pad)
    y1 = int(y1 - pad)
    x2 = int(x2 + pad)
    y2 = int(y2 + pad)

    # 2. 이미지 밖으로 나간 좌표를 다시 안으로 넣음
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(w, x2)
    y2 = min(h, y2)

    # roi 이상한 경우: 그냥 검은 이미지 반환해서 에러 방지
    if x2 <= x1 or y2 <= y1:
        canvas = np.zeros((target_size, target_size, 3), dtype=np.uint8)
        roi_info = None
        return canvas, roi_info

    # 3. 실제로 사람 부분만 crop
    roi = frame[y1:y2, x1:x2]

    # 4. crop된 이미지의 높이, 너비: 비율 유지하면서 resize하기 위해 사용
    roi_h, roi_w = roi.shape[:2]

    scale = target_size / max(roi_h, roi_w)
    new_w = max(1, int(roi_w * scale))
    new_h = max(1, int(roi_h * scale))

    roi_resized = cv2.resize(roi, (new_w, new_h))

    # 5. padding해서 정사각형 만들기
    # 256×256 검은 배경 생성
    canvas = np.zeros((target_size, target_size, 3), dtype=np.uint8)

    # 가운데 정렬을 위한 위치 계산
    x_offset = (target_size - new_w) // 2
    y_offset = (target_size - new_h) // 2

    # resize된 이미지를 중앙에 배치
    canvas[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = roi_resized

    # 6. roi_info 생성
    roi_info = {
        "x1": x1,
        "y1": y1,
        "roi_w": roi_w,
        "roi_h": roi_h,
        "scale": scale,
        "x_offset": x_offset,
        "y_offset": y_offset,
        "target_size": target_size
    }

    return canvas, roi_info


################################################################
################################################################
################################################################
# 좌우 반전 

def unify_left_all(all_landmarks, bat_positions, bat_angles, W):
    """
    왼손 타자 데이터를 오른손 기준으로 변환

    all_landmarks: (T, N, 4)  # (x, y, z, visibility)
    bat_positions: (T, 2) 또는 (T, 3)
    bat_angles: (T,)
    W: 원본 frame width
    """

    # -----------------------------
    # 1. landmark x좌표 반전
    # -----------------------------
    flipped_landmarks = all_landmarks.copy()

    # x 좌표: W - x
    flipped_landmarks[:, :, 0] = W - flipped_landmarks[:, :, 0]

    # -----------------------------
    # 2. 좌/우 landmark swap 
    # -----------------------------
    # MediaPipe 기준 index
    
    '''
    norm_left_shoulder, norm_right_shoulder,
    norm_left_elbow, norm_right_elbow,
    norm_left_wrist, norm_right_wrist,
    norm_left_hip, norm_right_hip,
    norm_left_knee, norm_right_knee,
    norm_left_ankle, norm_right_ankle
    '''
    
    LEFT_RIGHT_PAIRS = [
        (0, 1),  # shoulder
        (2, 3),  # elbow
        (4, 5),  # wrist
        (6, 7),  # hip
        (8, 9),  # knee
        (10, 11),  # ankle
    ]

    for l, r in LEFT_RIGHT_PAIRS:
        flipped_landmarks[:, [l, r], :] = flipped_landmarks[:, [r, l], :]

    # -----------------------------
    # 3. bat position x좌표 반전
    # -----------------------------
    # flipped_bat_positions = bat_positions.copy()

    # if flipped_bat_positions is not None:
    #     flipped_bat_positions[..., 0] = W - flipped_bat_positions[..., 0]

    # -----------------------------
    # 4. bat angle 반전
    # -----------------------------
    if bat_angles is not None:
        flipped_bat_angles = -bat_angles.copy()
        flipped_bat_angles = (flipped_bat_angles + 180) % 360 - 180
    else:   
        flipped_bat_angles = None

    return flipped_landmarks, flipped_bat_angles


