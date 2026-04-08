import numpy as np
import pandas as pd
from scipy.signal import savgol_filter

# 결측값 -> 선형 보간
def interpolate_coordinates(df, max_gap=4):
    """
    좌표 데이터프레임의 결측치를 선형 보간하고, 
    지정된 길이 이상의 연속된 결측 구간 프레임 번호를 반환한다.
    
    [parameter]
      df: 보간할 데이터프레임 (Player 또는 Bat)
      max_gap: 이 프레임 수 이상 연속 결측 시 플래그에 기록 (기본값 4)
      
    [return]
      dataFrame
    """
    
    # 원본 데이터를 훼손하지 않기 위해 복사본 생성
    result_df = df.copy()
    
    # 'frame' 컬럼을 제외한 나머지 좌표 컬럼 이름만 추출 (xmin, ymin... 또는 x1, y1...)
    coord_cols = [col for col in result_df.columns if col != 'frame']
    
    # 데이터가 아예 없는 경우 그대로 반환
    if result_df.empty or len(coord_cols) == 0:
        return result_df, []

    # 1. 긴 결측 구간 찾기 (플래그용)
    # 첫 번째 좌표 컬럼(예: xmin 또는 x1)을 기준으로 결측 여부(NaN) 확인
    ref_col = coord_cols[0]
    is_na = result_df[ref_col].isna()
    
    # 연속된 결측 구간을 그룹화
    na_groups = (is_na != is_na.shift()).cumsum()
    
    long_missing_flags = []
    # 결측치(True)인 그룹들만 모아서 검사
    for _, group in result_df[is_na].groupby(na_groups):
        if len(group) >= max_gap:
            # max_gap 이상 연속 결측된 프레임 번호들을 리스트에 추가
            long_missing_flags.extend(group['frame'].tolist())
            
    # 2. 선형 보간 수행
    # method='linear': 점과 점 사이를 직선으로 채움
    # limit_direction='both': 영상의 맨 처음이나 맨 끝에 결측이 있어도 채워줌
    result_df[coord_cols] = result_df[coord_cols].interpolate(method='linear', limit_direction='both')
    
    return result_df, long_missing_flags


# 이상치 -> 스무딩 필터 적용
def apply_smoothing_filter(df, window_length=7, polyorder=2):
    """
    보간된 좌표 데이터프레임에 Savitzky-Golay 필터를 적용하여
    튀는 값(노이즈)을 부드럽게 보정한다.
    
    [parameter]
      df: 보간이 완료된 데이터프레임
      window_length: 스무딩에 사용할 프레임 윈도우 크기 (무조건 홀수여야 함. 기본값 7)
      polyorder: 다항식 차수 (기본값 2. 야구 스윙 궤적에는 2~3이 적당함)
    
    [return]
      dataFrame
    """
    
    result_df = df.copy()
    
    # 'frame' 컬럼을 제외한 좌표 컬럼 인식
    coord_cols = [col for col in result_df.columns if col != 'frame']
    
    if result_df.empty or len(coord_cols) == 0:
        return result_df

    # window_length는 데이터의 총 길이보다 작거나 같아야 하며, 무조건 '홀수'여야 함
    n_samples = len(result_df)
    current_window = window_length
    
    if n_samples < current_window:
        # 데이터가 너무 짧으면 윈도우 크기를 데이터 길이에 맞게 줄임
        current_window = n_samples if n_samples % 2 != 0 else n_samples - 1

    # 윈도우 크기가 다항식 차수(polyorder)보다 작거나 같아지면 필터 적용 불가
    if current_window <= polyorder:
        print("[경고] 추출된 프레임 수가 너무 적어 스무딩 필터를 적용하지 않고 건너뜁니다.")
        return result_df

    # 각 좌표 컬럼마다 독립적으로 스무딩 필터 적용
    for col in coord_cols:
        result_df[col] = savgol_filter(result_df[col], window_length=current_window, polyorder=polyorder)

    return result_df

def process_angle_unwrapping(df, angle_col='angle'):
    """
    불연속적인 각도(r) 데이터를 연속적인 곡선으로 펼쳐준다.
    ex) 
    추출 값 88 -> 89 -> -89 -> -88 
    보정 값 88 -> 89 -> 91 -> 92
    
    [parameter]
      df : 보정할 데이터프레임
      angle_col : 각도 저장된 column (radian 단위)
    
    [return]
      dataFrame
    """
    # YOLO의 r 값은 Radian 단위 / period는 np.pi (180도)
    
    result_df = df.copy()
    
    # 1. 값이 존재하는(NaN이 아닌) 행의 인덱스와 데이터만 추출
    valid_mask = result_df[angle_col].notna()
    valid_angles = result_df.loc[valid_mask, angle_col].values
    
    if len(valid_angles) == 0:
        return result_df
        
    # 2. 정상 각도들에 대해서만 Unwrap 수행
    unwrapped_valid_angles = np.unwrap(valid_angles, period=np.pi)
    
    # 3. 쫙 펴진 각도를 원래 자리에 덮어쓰기 (NaN 자리는 그대로 NaN 유지됨)
    result_df.loc[valid_mask, angle_col] = unwrapped_valid_angles
    
    return result_df

def enforce_bbox_boundaries(df, img_width, img_height):
    """
    스무딩 처리된 바운딩 박스(xyxy) 좌표가 
    영상 화면 밖으로 나가거나 역전(min > max)되는 현상 방지
    
    [parameter]
      df: Player의 좌표 데이터프레임 (xmin, ymin, xmax, ymax 포함)
      img_width: 영상의 가로 픽셀 크기
      img_height: 영상의 세로 픽셀 크기
    [return]
      dataFrame
    """
    # 원본 데이터를 훼손하지 않기 위해 복사본 생성
    result_df = df.copy()
    
    # 데이터가 비어있거나 필수 컬럼이 없으면 그대로 반환
    required_cols = ['xmin', 'ymin', 'xmax', 'ymax']
    if result_df.empty or not all(col in result_df.columns for col in required_cols):
        return result_df

    # 1. 화면 밖으로 나가는 좌표 방지 (Clipping)
    result_df[['xmin', 'xmax']] = result_df[['xmin', 'xmax']].clip(0, img_width)
    result_df[['ymin', 'ymax']] = result_df[['ymin', 'ymax']].clip(0, img_height)

    # 2. 좌표 역전 방지 (xmin이 xmax 이상이 되지 않도록 강제 조정)
    # 최소한 1픽셀의 너비와 높이는 유지하도록 처리
    result_df['xmin'] = np.minimum(result_df['xmin'], result_df['xmax'] - 1)
    result_df['ymin'] = np.minimum(result_df['ymin'], result_df['ymax'] - 1)

    return result_df