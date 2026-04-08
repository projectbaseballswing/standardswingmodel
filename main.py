from modules.yolo_obb_tracker import track_target_player_and_bat
from modules.open_cv import get_video_size
from modules.preprocessing import preprocess_player, preprocess_bat
from ultralytics import YOLO

def main():
    video_path = "" # 영상 1개의 경로 입력
    yolo_model_path = "weights/custom_yolo_model.pt"
    yolo_model = YOLO(yolo_model_path)
    
    v_width, v_height = get_video_size(video_path)
    
    # Target player, bat 추적 및 좌표 추출
    extracted_data = track_target_player_and_bat(video_path, yolo_model)
    
    if extracted_data is None:
        print("Target Not Found")
        return
    
    # Player 전처리
    # 결측치 보정 -> 이상치 보정 -> 뒤틀림 및 영역 벗어남 보정 -> df to np
    player_df = extracted_data["player"]
    player_np, p_flags = preprocess_player(player_df, v_width, v_height)
    
    # Bat 전처리
    # 각도 언래핑(0~90도를 연속값으로 보정) -> 결측치 보정 -> 이상치 보정 -> df to np
    bat_df = extracted_data["bat"]
    bat_np = preprocess_bat(bat_df)

    '''
    [ 여기까지 진행했을 때 변수 목록 ]
    player_np : player xyxy 데이터 (numpy) [xmin, ymin, xmax, ymax]
    p_flags : player의 결측 프레임 목록 (array), ** frame은 0이 아닌 1부터 시작함!! **
    bat_np : bat xywhr 데이터 (numpy) [cx, cy, w, h, r]
    '''
    
if __name__  == "__main__":
    main()