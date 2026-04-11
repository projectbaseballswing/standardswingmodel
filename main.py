from modules.open_cv import process_video
from ultralytics import YOLO

def main():
    video_path = "" # 영상 1개의 경로 입력
    yolo_model_path = "weights/custom_yolo_model.pt"
    yolo_model = YOLO(yolo_model_path)
    mediapipe_model_path = "models/pose_landmarker.task"

    player_df, bat_df = process_video(video_path, yolo_model)
    print(player_df)
    
if __name__  == "__main__":
    main()