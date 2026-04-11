from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import os

DEFAULT_MEDIAPIPE_MODEL_PATH = "models/pose_landmarker.task"

def create_landmarker(model_path: str =DEFAULT_MEDIAPIPE_MODEL_PATH):
    """
    MediaPipe PoseLandmarker 생성 함수
    - model_path는 main.py에서 전달받는 구조로 통일
    """
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"모델 파일을 찾지 못했습니다: {model_path}")

    base_options = python.BaseOptions(model_asset_path=model_path)
    options = vision.PoseLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
        output_segmentation_masks=False,
    )
    return vision.PoseLandmarker.create_from_options(options)