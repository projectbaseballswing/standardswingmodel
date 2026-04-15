import numpy as np
import pandas as pd
from scipy.signal import savgol_filter

# 결측값 -> 선형 보간
def _interpolate_coordinates(df):
    """
    좌표 데이터프레임의 결측치를 선형 보간하고, 
    지정된 길이 이상의 연속된 결측 구간이 존재하는지 여부를 반환한다.
    
    [parameter]
      df: 보간할 데이터프레임 (Player 또는 Bat)
      
    [return]
      result_df (dataFrame)
      max_missing_gap (int) : 결측치가 연속된 최대 프레임 수
    """
    
    # 원본 데이터를 훼손하지 않기 위해 복사본 생성
    result_df = df.copy()
    
    # 'frame' 컬럼을 제외한 나머지 좌표 컬럼 이름만 추출 (xmin, ymin... 또는 x1, y1...)
    coord_cols = [col for col in result_df.columns if col != 'frame']
    
    # 데이터가 아예 없는 경우 반환
    if result_df.empty or len(coord_cols) == 0:
        return None, 0

    # 1. 연속 결측 프레임(Max Gap) 최대값 계산
    ref_col = coord_cols[0]
    is_missing = result_df[ref_col].isna()
    
    if not is_missing.any():
      max_missing_gap = 0
    else:
      max_missing_gap = int(is_missing.groupby((~is_missing).cumsum()).sum().max())
            
    # 2. 선형 보간 수행
    # method='linear': 점과 점 사이를 직선으로 채움
    # limit_direction='both': 영상의 맨 처음이나 맨 끝에 결측이 있어도 채워줌
    result_df[coord_cols] = result_df[coord_cols].interpolate(method='linear', limit_direction='both')
    
    return result_df, max_missing_gap

# 이상치 -> 스무딩 필터 적용
def _apply_smoothing_filter(df, window_length=7, polyorder=2):
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

def _process_angle_unwrapping(df, angle_col='r', width_col='w', height_col='h'):
    """
    불연속적인 각도(r) 데이터를 연속적인 곡선으로 펼쳐주고, 배트 길이를 반영해 각도를 보정한다.
    (yolo obb model은 0-90도의 각도만 인식하기 때문)
    
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
    
    # 1. 값이 존재하는(NaN이 아닌) 유효한 데이터 마스크 추출
    valid_mask = result_df[angle_col].notna() & result_df[width_col].notna() & result_df[height_col].notna()
    
    if not valid_mask.any():
        return result_df
        
    # 장축/단축 보정 (Axis Alignment)
    # 배트는 항상 height보다 width가 큼 -> width가 긴 쪽이 되도록 각도 통일
    swap_mask = valid_mask & (result_df[width_col] < result_df[height_col])
    
    if swap_mask.any():
        # 1) 각도에 90도(pi/2)를 더해서 장축 기준으로 돌려줌
        result_df.loc[swap_mask, angle_col] += (np.pi / 2)
        
        # 2) w와 h의 값을 서로 맞바꿈
        temp_w = result_df.loc[swap_mask, width_col].copy()
        result_df.loc[swap_mask, width_col] = result_df.loc[swap_mask, height_col]
        result_df.loc[swap_mask, height_col] = temp_w
        
    # 3) 90도를 더하면서 기존 범위를 벗어난 값들을 다시 -90도 ~ 90도(-pi/2 ~ pi/2) 안으로 정규화
    result_df.loc[valid_mask, angle_col] = (result_df.loc[valid_mask, angle_col] + np.pi / 2) % np.pi - np.pi / 2

    # 언래핑 (Unwrapping)
    # 4. 축이 모두 통일된 정상 각도들에 대해서만 Unwrap 수행
    valid_angles = result_df.loc[valid_mask, angle_col].values
    unwrapped_valid_angles = np.unwrap(valid_angles, period=np.pi)
    
    # 5. 쫙 펴진 각도를 원래 자리에 덮어쓰기
    result_df.loc[valid_mask, angle_col] = unwrapped_valid_angles
    
    return result_df

def _enforce_bbox_boundaries(df, img_width, img_height):
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

def preprocess_player(player_df, img_width, img_height):
    '''
    Player 좌표 데이터 전처리 프로세스
    결측치 보정 -> 이상치 보정 -> 뒤틀림 및 영역 벗어남 보정 -> df to np
    
    [parameter]
      player_df : yolo model로 추출된 player 좌표 데이터
      img_width, img_height : 영상 크기
      
    [return]
      player_np : 전처리 완료된 numpy
      is_max_gap_exceeded : 연속된 결측 프레임이 임계값 이상 발견될 경우
    '''
    player_interp, is_max_gap_exceeded = _interpolate_coordinates(player_df)
    player_smooth = _apply_smoothing_filter(player_interp, window_length=7, polyorder=2)
    
    final_player_df = _enforce_bbox_boundaries(player_smooth, img_width, img_height)
    player_np = final_player_df.to_numpy()[:,1:]
    
    return player_np, is_max_gap_exceeded

def preprocess_bat(bat_df):
    '''
    Bat 좌표 데이터 전처리 프로세스
    각도 언래핑(0~90도를 연속값으로 보정) -> 결측치 보정 -> 이상치 보정 -> df to np
    
    [parameter]
      bat_df : yolo model로 추출된 bat 좌표 데이터
      
    [return]
      bat_np : 전처리 완료된 numpy
    '''
    bat_unwrap = _process_angle_unwrapping(bat_df)
    bat_interp, b_flags = _interpolate_coordinates(bat_unwrap) 
    final_bat_df = _apply_smoothing_filter(bat_interp, window_length=7, polyorder=3)  
    bat_np = final_bat_df.to_numpy()[:,1:]
    
    return bat_np