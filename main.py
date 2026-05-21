from modules.open_cv import process_all_videos
from visualizations.object_tracking import object_tracking
from ultralytics import YOLO
import os
import json

def main():
    
    # 경로에 맞게 수정 
    video_dir= "" # 영상 1개의 경로 입력
    
    # 결과 저장 폴더
    save_dir = "" 

    metadata_path = ""

    yolo_model_path = "./weights/custom_yolo_model5.pt"
    yolo_model = YOLO(yolo_model_path)
    # player_np, bat_np = process_video(video_dir, yolo_model)
    
    process_all_videos(
        video_dir=video_dir,
        yolo_model=yolo_model,
        save_dir=save_dir,
        metadata_path=metadata_path
    )
    
    # if player_np is None or bat_np is None:
    #     print("Player 또는 Bat 데이터가 충분하지 않아 시각화를 진행할 수 없습니다.")
    #     return
    
    # print("뷰어를 실행합니다. 영상을 끄려면 창을 선택하고 'q' 키를 누르세요.")
        
    # # 시각화 테스트 함수 호출
    # object_tracking(video_path, player_np, bat_np)

if __name__ == "__main__":
    main()