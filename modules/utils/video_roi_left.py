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


################################################################
################################################################
################################################################

# 정규화 함수
def normalize_landmarks_sequence(all_landmarks, visibility, eps=1e-8):
    if len(all_landmarks) == 0:
        return all_landmarks

    # 기준 프레임 선택: 프레임 중 가장 기준으로 잡기 좋은 프레임 선택
    ref_idx = select_reference_frame(all_landmarks, visibility)
    if ref_idx is None:
        return all_landmarks

    ref_frame = all_landmarks[ref_idx]

    # 몸 기준으로 좌표축을 만듦
    basis = build_reference_basis(ref_frame, eps)
    if basis is None:
        return all_landmarks

    # 사람 크기 통일
    body_scale = compute_body_scale(all_landmarks, eps)
    if not np.isfinite(body_scale) or body_scale < eps:
        return all_landmarks

    # 전체 정규화
    return apply_normalization(all_landmarks, basis, body_scale, eps)

################################################################

# 기준 프레임 선택 
def select_reference_frame(all_landmarks, visibility=None):
    '''
    기준 좌표계를 만들 reference frame 선택.
      - 양쪽 hip / shoulder가 모두 valid해야 함
      - 그중 visibility 평균이 가장 높은 프레임을 선택    
    '''

    # 필요한 관절 index
    REQUIRED_IDXS = [6, 7, 0, 1]  # left_hip, right_hip, left_shoulder, right_shoulder

    # 가장 좋은 프레임 index 저장
    best_idx = None
    # 최고 점수 저장 변수 / 처음은 무한
    best_score = -np.inf

    # 모든 프레임 순회
    for i, frame in enumerate(all_landmarks):

        # 이 프레임이 유효한지 체크용 변수
        valid = True
        # visibility 값들 모을 리스트
        vis_list = []

        # 필요한 관절 4개만 검사
        for j in REQUIRED_IDXS:
            # 해당 관절의 (x, y, z) 좌표 가져오기
            coords = frame[j]

            # 좌표 유효성 체크
            # np.isfinite(coords): 각 값이 정상적인 숫자인지 검사 -> all: 배열 안의 값이 전부 True인지 확인
            if not np.all(np.isfinite(coords)):
                # 이 관절 좌표 중 하나라도 NaN이나 Inf가 있으면 더 검사할 필요 없음
                valid = False
                break

            # visibility 가져오기 
            if visibility is not None:
                # 해당 관절의 신뢰도 가져오기
                vis = float(visibility[i][j])
            # visibility 없으면 NaN 처리
            else:
                vis = np.nan

            vis_list.append(vis)

        # 프레임이 invalid면 → 스킵
        if not valid:
            continue

        # visibility 평균 점수 / NaN은 자동 무시
        if len(vis_list) > 0:
            mean_vis = float(np.nanmean(vis_list))
        # 리스트 비었으면 최악 점수
        else:
            mean_vis = -np.inf

        # visibility가 전부 nan이면 fallback
        if not np.isfinite(mean_vis):
            mean_vis = 0.0

        # 최고 프레임 선택
        if mean_vis > best_score:
            best_idx = i
            best_score = mean_vis

    return best_idx

################################################################

# 사람 기준 좌표계 만들기: 사람의 방향을 통일시킬 수 있는 기준 좌표를 만든다. 
def build_reference_basis(frame, eps=1e-8):
    """
    reference frame에서 기준 좌표계의 basis 생성.

    - x축: 오른쪽 hip - 왼쪽 hip
    - y축: hip center -> shoulder center 방향을 보조축으로 사용
    - z축: x축과 torso 방향의 외적
    """

    # index 매핑
    lhip = frame[6] # 왼쪽 hip
    rhip = frame[7] # 오른쪽 hip
    lsho = frame[0] # 왼쪽 shoulder
    rsho = frame[1] # 오른쪽 shoulder 

    # 좌표 유효성 검사: 4개 관절의 모든 값이 정상인지 확인
    if not np.all(np.isfinite(np.concatenate([lhip, rhip, lsho, rsho]))):
        return None

    # 중심 계산
    hip_center = (lhip + rhip) / 2.0
    shoulder_center = (lsho + rsho) / 2.0

    # x축: 몸의 가로 방향: 좌우 기준 고정
    x_axis = normalize_vec(rhip - lhip, eps)
    # 길이가 0이거나 이상하면 → 바로 none반환
    if x_axis is None:
        return None

    # torso 방향: 몸의 위쪽 방향 (임시 y축)
    y_temp = shoulder_center - hip_center

    # z축 (몸 앞/뒤 방향): 앞뒤 기준 고정
    # x와 y에 수직인 방향 생성: 정확한 3D 좌표축 완성
    z_axis = normalize_vec(np.cross(x_axis, y_temp), eps)
    if z_axis is None:
        return None

    y_axis = normalize_vec(np.cross(z_axis, x_axis), eps)
    if y_axis is None:
        return None

    # 최종 좌표계 반환
    return np.stack([x_axis, y_axis, z_axis], axis=1)

################################################################

# 길이를 1로 만든다
def normalize_vec(v, eps=1e-8):
    """
    벡터를 정규화해서 반환.
    길이가 0에 가깝거나 비정상 값이면 None 반환.

    v: np.ndarray (shape: (3,))
    v: 벡터 (예: [x, y, z])
    """

    # 벡터 길이 계산
    norm = np.linalg.norm(v)

    # 유효성 검사: 값이 정상인지 확인 & 길이가 너무 작은지 확인
    if not np.isfinite(norm) or norm < eps:
        return None

    # 정규화 (길이 1로)
    return v / norm


################################################################

def compute_body_scale(all_landmarks, eps=1e-8):
    """
    사람 body scale을 robust하게(이상치에 강하게 계산) 계산

      - 프레임마다 신체 크기 후보(hip width, shoulder width, torso length)를 계산하고,
        그 중앙값들의 중앙값을 최종 body scale로 사용.
      - 이상치 제거 + median of median 구조
    """

    # 각 프레임에서 계산된 body 크기를 저장할 공간
    scales = []

    for frame in all_landmarks:
        # 관절 좌표 꺼내기
        lhip = frame[6]
        rhip = frame[7]
        lsho = frame[0]
        rsho = frame[1]

        # 좌표 유효성 검사
        if not np.all(np.isfinite(np.concatenate([lhip, rhip, lsho, rsho]))):
            continue

        # 중심 계산
        hip_center = (lhip + rhip) / 2.0
        shoulder_center = (lsho + rsho) / 2.0

        # 길이 계산
        hip_width = np.linalg.norm(rhip - lhip) # 엉덩이 좌우 거리
        shoulder_width = np.linalg.norm(rsho - lsho) # 어깨 좌우 거리
        torso_len = np.linalg.norm(shoulder_center - hip_center) # 몸통 길이 (어깨 ↔ 엉덩이)

        # 후보 필터링: 값이 정상이고 (finite) 너무 작은 값 아닌 것만 사용
        candidates = [
            v for v in [hip_width, shoulder_width, torso_len]
            if np.isfinite(v) and v > eps
        ]

        # 최소 2개 이상 있어야 사용
        if len(candidates) < 2:
            continue

        # 1차 robust: 후보 3개 중 중앙값(median) 사용
        frame_scale = float(np.median(candidates))

        scales.append(frame_scale)

    # 모든 프레임이 이상하면 기본값 1.0 반환
    if len(scales) == 0:
        return 1.0

    # 2차 robust (전체): 프레임별 scale들 중 중앙값
    return float(np.median(scales))

################################################################

# 최종 정규화 코드 
def apply_normalization(all_landmarks, basis, body_scale, eps=1e-8):
    """
    landmark sequence 정규화
    각 프레임 landmark를
    1) hip center를 원점으로 이동
    2) reference basis 좌표계로 회전
    3) robust body scale로 나누어 크기 정규화

    all_landmarks: List[np.ndarray]  # 각 프레임 (N, 3)
    basis: np.ndarray (3, 3)
    body_scale: float

    return:
        List[np.ndarray] (정규화된 landmark)
    """

    # 결과 저장할 리스트
    normalized_sequence = []

    for frame in all_landmarks:
        # 프레임이 비어있거나 이상하면 그냥 그대로 넣고 다음 프레임으로 넘어감
        if frame is None or len(frame) == 0:
            normalized_sequence.append(frame)
            continue

        # numpy 배열로 변환(혹시나 안되어 있으면)
        frame = np.asarray(frame)

        # 좌표 / mask 분리: mask는 정규화하면 안됨
        coords = frame[:, :3]   # (N, 3)
        extra  = frame[:, 3:]   # (N, 1) or more

        # 왼쪽/오른쪽 hip 좌표 가져오기 
        lhip = coords[6]
        rhip = coords[7]

        # 좌표가 NaN / inf인지 체크 -> 이상하면 그냥 원래 좌표로 넣음 
        if not np.all(np.isfinite(lhip)) or not np.all(np.isfinite(rhip)):
            normalized_sequence.append(frame)
            continue

        # hip center (원점 이동)
        hip_center = (lhip + rhip) / 2.0 # 몸의 기준 원점
        # 모든 관절을 hip 기준으로 이동: 사람 위치 제거 & (0,0,0)이 몸 중심이 됨
        rel_world = coords - hip_center  # (N, 3)

        # 기준 좌표계로 회전: 사람 방향 정렬 & 카메라 방향 영향 제거
        rel = rel_world @ basis  # (N, 3) / @: 행렬 곱
        # (= basis.T @ rel_world.T 한 거랑 동일한 효과)

        # scale 정규화: 크기 정규화 -> 키 차이 제거 / 모두 같은 크기로 맞춤
        norm_coords = rel / body_scale

        # 다시 좌표 + mask합치기 
        norm_frame = np.concatenate([norm_coords, extra], axis=1)

        normalized_sequence.append(norm_frame)

    return normalized_sequence



