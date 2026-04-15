from modules.open_cv import process_video
from visualizations.object_tracking import object_tracking
from ultralytics import YOLO

def main():
    video_path = "" # 영상 1개의 경로 입력
    yolo_model_path = "weights/custom_yolo_model2.pt"
    yolo_model = YOLO(yolo_model_path)
    player_np, bat_np = process_video(video_path, yolo_model)
    
    if player_np is None or bat_np is None:
        print("Player 또는 Bat 데이터가 충분하지 않아 시각화를 진행할 수 없습니다.")
        return
    
    print("뷰어를 실행합니다. 영상을 끄려면 창을 선택하고 'q' 키를 누르세요.")
        
    # 시각화 테스트 함수 호출
    object_tracking(video_path, player_np, bat_np)

if __name__ == "__main__":
    main()