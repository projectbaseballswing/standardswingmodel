from modules.open_cv import process_all_videos
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
    
    process_all_videos(
        video_dir=video_dir,
        yolo_model=yolo_model,
        save_dir=save_dir,
        metadata_path=metadata_path
    )

if __name__ == "__main__":
    main()