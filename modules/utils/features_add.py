# final_data = make_features(all_landmarks, bat_angles, bat_positions, dt)
def make_features_single_video(all_landmarks, bat_angles, bat_positions, visibility, dt):


    '''
    all_landmarks: numpy 
    bat_angles: numpy
    bat_positions: numpy

    '''

    # 1. 임팩트 찾기
    # 배트 속도가 가장 빠른 순간 = 임팩트라고 가정
    impact_idx = _find_impact_frame(bat_positions)

    # 2. 정렬 + 길이 통일
    # 임팩트를 중심으로 앞뒤 동일하게 자름
    target_len = 80
    pre_ratio = 0.75
    lm = _align_sequence(all_landmarks, impact_idx, target_len, pre_ratio)
    angle = _align_sequence(bat_angles, impact_idx, target_len, pre_ratio)
    pos = _align_sequence(bat_positions, impact_idx, target_len, pre_ratio)
    vis = _align_sequence(visibility, impact_idx, target_len, pre_ratio)

    # 한 관절이 x,y,z,visibility 순서로 피처가 되도록 설정 
    coords = lm        # (T,12,3)
    mask   = vis       # (T,12)

    coords_with_mask = np.concatenate([
        coords,
        mask[..., None]
    ], axis=2)  # (T,12,4)

    # [x,y,z,visibilty] -> [x],[y],[z]... 처럼 하나의 피처가 될수 있도록 바꿈 
    coords_feat = coords_with_mask.reshape(len(coords), -1)

    # 3. 피처 생성
    # lm: 관절 좌표 / angle: 배트 각도 / pos: 배트 위치

    # 관절 피처 생성
    '''
    norm_left_shoulder, norm_right_shoulder,
    norm_left_elbow, norm_right_elbow,
    norm_left_wrist, norm_right_wrist,
    norm_left_hip, norm_right_hip,
    norm_left_knee, norm_right_knee,
    norm_left_ankle, norm_right_ankle

    '''
    left_shoulder  = lm[:, 0, :]
    right_shoulder = lm[:, 1, :]

    left_elbow  = lm[:, 2, :]
    right_elbow = lm[:, 3, :]

    left_wrist  = lm[:, 4, :]
    right_wrist = lm[:, 5, :]

    left_hip  = lm[:, 6, :]
    right_hip = lm[:, 7, :]

    left_knee  = lm[:, 8, :]
    right_knee = lm[:, 9, :]

    left_ankle  = lm[:, 10, :]
    right_ankle = lm[:, 11, :]

    angle_left_elbow = _calculate_angle(left_shoulder, left_elbow, left_wrist)
    angle_right_elbow = _calculate_angle(right_shoulder, right_elbow, right_wrist)

    angle_left_knee = _calculate_angle(left_hip, left_knee, left_ankle)
    angle_right_knee = _calculate_angle(right_hip, right_knee, right_ankle)

    # 몸통(상체)이 어느 방향을 보고 있는지 (회전 방향)
    angle_torso = _calculate_torso_angle(left_shoulder, right_shoulder,left_hip, right_hip)

    # 회전 각도 피처 생성
    angle_hip_rotation = _calculate_rotation_angle(left_hip, right_hip)
    angle_shoulder_rotation = _calculate_rotation_angle(left_shoulder, right_shoulder)

    # 회전 속도 계산: 각도가 얼마냐 빨리 변하냐
    wrist_center = (left_wrist + right_wrist) / 2

    hip_rotation_velocity, shoulder_rotation_velocity, wrist_velocity = _compute_all_velocities(
    left_hip, right_hip,
    left_shoulder, right_shoulder,
    wrist_center,
    dt)

    # 상대 좌표 계산
    # center 계산
    shoulder_center = (left_shoulder + right_shoulder) / 2
    hip_center = (left_hip + right_hip) / 2
    wrist_center = (left_wrist + right_wrist) / 2
    ankle_center = (left_ankle + right_ankle) / 2
    
    # 상체: 어깨 기준 손 위치
    rel_wrist = wrist_center - shoulder_center

    # 하체: 골반 기준 발 위치
    rel_ankle = ankle_center - hip_center

    # 몸 기울기: 골반 기준 어깨 위치
    rel_shoulder = shoulder_center - hip_center

    # 배트 계산
    # 각속도 크기(bat speed) + 각속도 반환(angular_velocity)
    bat_speed, bat_angular_velocity = _compute_bat_speed(angle, dt)


    # 피처 합치기
    features = np.concatenate([

    # 1. landmark (flatten)
    coords_feat,

    # 2. relative positions
    rel_wrist,
    rel_ankle,
    rel_shoulder,

    # 3. angles (T,1)
    angle_left_elbow[:, None],
    angle_right_elbow[:, None],
    angle_left_knee[:, None],
    angle_right_knee[:, None],
    angle_torso[:, None],
    angle_hip_rotation[:, None],
    angle_shoulder_rotation[:, None],

    # 4. velocities (T,1)
    hip_rotation_velocity[:, None],
    shoulder_rotation_velocity[:, None],
    wrist_velocity[:, None],

    # 5. bat features
    bat_speed[:, None],
    bat_angular_velocity[:, None],

    ], axis=1)

    return features  # (T, F)


#################################
#################################
#################################

# 임팩트 찾기
# 배트 속도가 가장 빠른 프레임 = 임팩트
# pos: 배트 위치로 찾음
def _find_impact_frame(pos):
    speeds = []
    for i in range(1, len(pos)):
        # pos[i] - pos[i-1] → 이동 벡터
        # # np.linalg.norm(...) → 벡터의 길이(크기)를 구하는 함수
        dist = np.linalg.norm(pos[i] - pos[i-1])
        speeds.append(dist)
    # np.argmax(speeds) → 속도가 최대인 index 반환(프레임은 1부터 시작해서 +1해줌)
    return np.argmax(speeds) + 1

# 정렬 + 길이 통일
# 임팩트를 중심으로 시퀀스를 잘라서 길이를 딱 맞춤: 80으로 통일(임팩트기준 앞:60, 뒤:20)
# seq: 시계열 데이터 (landmarks / angle / pos 중 하나) / impact_idx: 임팩트 프레임 번호 / target_len: 최종 길이
def _align_sequence(seq, impact_idx, target_len=80, pre_ratio=0.75):
    half = target_len // 2 # 40
    
    # 앞/뒤 필요한 길이
    pre_len = int(target_len * pre_ratio)   # 앞 (60)
    post_len = target_len - pre_len         # 뒤 (20)
    
    # 실제 가져올 수 있는 범위
    start = max(0, impact_idx - pre_len)
    end = min(len(seq), impact_idx + post_len)

    aligned = seq[start:end]
    
    # 안전장치
    if len(aligned) == 0:
        return np.zeros((target_len, *seq.shape[1:]))

    # 실제 확보된 길이
    left_actual = impact_idx - start
    right_actual = end - impact_idx
    
    # 부족한 길이 계산
    left_pad_len = pre_len - left_actual
    right_pad_len = pre_len - right_actual

    # 길이가 부족한 경우 패딩: 앞이나 뒤가 잘려서 80보다 짧아질 수 있음
    if left_pad_len > 0:
        left_pad = np.repeat(aligned[0:1], left_pad_len, axis=0)
        aligned = np.concatenate([left_pad, aligned], axis=0)

    if right_pad_len > 0:
        right_pad = np.repeat(aligned[-1:], right_pad_len, axis=0)
        aligned = np.concatenate([aligned, right_pad], axis=0)

    return aligned[:target_len]

#################################
#################################
#################################
# 관절 좌표 추가 피처 생성

def _calculate_angle(a, b, c):
    """
    a, b, c: (T, 3)
    b를 기준으로 각도 계산 (a-b-c)
    return: (T,)
    공식: cosθ = (A·B) / (|A||B|)
    """

    ba = a - b   # (T, 3)
    bc = c - b   # (T, 3)

    # 내적 (프레임별)
    dot = np.sum(ba * bc, axis=1)

    # 벡터 크기 (프레임별)
    norm_ba = np.linalg.norm(ba, axis=1)
    norm_bc = np.linalg.norm(bc, axis=1)
    
    # 분모 (0 방지)
    denom = norm_ba * norm_bc
    denom = np.where(denom < 1e-8, 1e-8, denom)

    cos_angle = dot / denom
    cos_angle = np.clip(cos_angle, -1.0, 1.0)
    
    angle = np.arccos(cos_angle)
    
    # NaN 방지: NaN(이상값)을 정상 숫자로 바꿔주는 함수
    angle = np.nan_to_num(angle)

    return np.degrees(angle)   # (T,)

def _calculate_torso_angle(left_shoulder, right_shoulder,
                          left_hip, right_hip):
    """
    골반 기준으로 상체가 어디 방향으로 돌아갔는지
    torso 방향 (hip_center → shoulder_center)
    x축 기준으로 측정됨
    z축 안쓰는 이유: 실제 거리 아님, 스케일이 x, y랑 다름, 노이즈 많음 > 쓰면 오히려 값이 튀어버림
    """

    shoulder_center = (left_shoulder + right_shoulder) / 2
    hip_center = (left_hip + right_hip) / 2

    # 골반 → 어깨 방향 벡터
    vec = shoulder_center - hip_center

    x = vec[:, 0]
    y = vec[:, 1]

    # 방향을 → 각도로 변환
    angle = np.arctan2(y, x)   
    # nan오류 방지: 0으로 바꿈
    angle = np.nan_to_num(angle)

    return np.degrees(angle)


def _calculate_rotation_angle(left_point, right_point):
    # x,y만 구할거임
  
    # 왼쪽 → 오른쪽 방향 벡터
    vec = right_point - left_point
    x = vec[:, 0]
    y = vec[:, 1]

    # 원점 (0,0)에서 (x, y) 방향으로 향하는 각도 계산
    angle = np.arctan2(y, x)   # 프레임별 계산  # y, x
    
    angle = np.nan_to_num(angle)
    
    # 오,왼 잘못 인식했을 때 등 각도가 튀어버리는 문제 발생 -> unwrap: 부드럽게 해줌
    angle = np.unwrap(angle)

    return np.degrees(angle)


def _compute_all_velocities(
    left_hip, right_hip,
    left_shoulder, right_shoulder,
    wrist_center,
    dt
):
    '''
    hip_rotation_velocity      → 골반이 얼마나 빠르게 도는지  
    houlder_rotation_velocity → 어깨가 얼마나 빠르게 도는지  
    wrist_velocity             → 손(배트)이 얼마나 빠르게 움직이는지
    '''
    

    # 1. 회전 각도 계산 함수
    def rotation_angle(left, right):
        vec = right - left               # (T, 2 or 3)
        x = vec[:, 0]
        y = vec[:, 1]
        # 각도 계산: 벡터가 x축 기준으로 얼마나 기울었는지
        return np.arctan2(y, x)       # (T,) rad

    # 2. 각도 계산 + unwrap
    # unwrap으로 튐 제거 > 다시 radian으로 바꿔줘야 함
    # 골반 방향 각도 계산
    hip_angle = np.unwrap(rotation_angle(left_hip, right_hip))
    # 어깨 방향 각도 계산
    shoulder_angle = np.unwrap(rotation_angle(left_shoulder, right_shoulder))


    # 3. 각속도 계산
    # 각도 변화량 계산
    hip_rotation_velocity = np.diff(hip_angle) / dt
    shoulder_rotation_velocity = np.diff(shoulder_angle) / dt
    
    # degree로 변환
    hip_rotation_velocity = np.degrees(hip_rotation_velocity)
    shoulder_rotation_velocity = np.degrees(shoulder_rotation_velocity)

    # 4. 손목 속도
    wrist_diff = np.diff(wrist_center, axis=0)   # (T-1, 2 or 3)
    # 이동 거리(벡터 길이) 계산
    wrist_velocity = np.linalg.norm(wrist_diff, axis=1) / dt

    # 5. 길이 맞추기: diff 때문에 길이가 하나 줄어듦, 앞에 0 추가
    hip_rotation_velocity = np.insert(hip_rotation_velocity, 0, 0)
    shoulder_rotation_velocity = np.insert(shoulder_rotation_velocity, 0, 0)
    wrist_velocity = np.insert(wrist_velocity, 0, 0)

    return hip_rotation_velocity, shoulder_rotation_velocity, wrist_velocity


#################################
#################################
#################################
# 배트 추가 피처 생성

def _compute_bat_speed(angle, dt): 
    """
    각속도 크기(bat speed) + 각속도 반환(angular_velocity)
    각속도로 사용
    각속도: 각도가 얼마나 빠르게 변하냐, 공식: 각도 변화량 / 시간
    angle: (T,) degree
    dt: float

    return:
        bat_speed (T,)
    """
    
    # 범위 정리 (-180 ~ 180)
    angle = (angle + 180) % 360 - 180

    # 1. rad로 변환
    angle_rad = np.radians(angle)

    # 2. unwrap: 각도 튐 제거
    angle_rad = np.unwrap(angle_rad)

    # 3. 각속도 계산
    angular_velocity = np.diff(angle_rad) / dt  # (T-1,)

    # 4. 길이 맞추기
    angular_velocity = np.insert(angular_velocity, 0, 0)

    # bat speed = 각속도
    bat_speed = np.abs(angular_velocity)

    return bat_speed, angular_velocity

