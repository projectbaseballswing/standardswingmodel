import cv2
import numpy as np
import math

def object_tracking(video_path, player_np, bat_np, window_name="Tracking Viewer"):
    """
    원본 영상 위에 Player(파란색)와 Bat(빨간색)의 Numpy 좌표 데이터를 겹쳐서 보여줍니다.
    'q' 키를 누르면 재생이 종료됩니다.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("에러: 비디오를 열 수 없습니다.")
        return

    frame_idx = 0
    
    # 두 배열 중 더 짧은 길이를 기준으로 재생 (혹은 영상 끝까지)
    max_frames = len(player_np) if player_np is not None else 0
    
    # 영상 재생 루프
    while True:
        ret, frame = cap.read()
        
        # 영상이 끝나거나 추적 데이터 길이를 넘어서면 종료
        if not ret or frame_idx >= max_frames:
            print("영상 재생이 끝났습니다.")
            break

        # --- 1. Player 그리기 (xyxy) ---
        if player_np is not None and frame_idx < len(player_np):
            p_coords = player_np[frame_idx]
            
            # 결측치(NaN)가 아닐 때만 그리기
            # (만약 배열에 frame 번호가 포함된 형태라면 p_coords[-4:] 처럼 뒤에서 4개만 가져오면 안전합니다)
            if not np.isnan(p_coords).any():
                # 좌상단, 우하단 좌표를 정수로 변환
                x1, y1, x2, y2 = map(int, p_coords[-4:])
                
                # 파란색 박스와 텍스트
                cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)
                cv2.putText(frame, "Player", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)

        # --- 2. Bat 그리기 (OBB: cx, cy, w, h, r) ---
        if bat_np is not None and frame_idx < len(bat_np):
            b_coords = bat_np[frame_idx]
            
            if not np.isnan(b_coords).any():
                cx, cy, w, h, r = map(float, b_coords[-5:])
                
                # 라디안(Radian)을 각도(Degree)로 변환
                angle_deg = math.degrees(r)
                
                # 중심점, (너비, 높이), 각도를 이용해 4개의 꼭짓점 계산
                rect = ((cx, cy), (w, h), angle_deg)
                box = cv2.boxPoints(rect)
                box = np.int32(box) # 정수형 배열로 변환
                
                # 빨간색 다각형(회전된 박스)과 텍스트
                cv2.drawContours(frame, [box], 0, (0, 0, 255), 2)
                cv2.putText(frame, "Bat", (int(cx), int(cy)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        # 화면 출력
        cv2.imshow(window_name, frame)
        
        # 키보드 입력 대기 (숫자를 줄이면 재생 속도가 빨라짐. 30ms = 약 33fps)
        key = cv2.waitKey(60) & 0xFF
        if key == ord('q'): # 'q'를 누르면 강제 종료
            print("사용자에 의해 재생이 중단되었습니다.")
            break
            
        frame_idx += 1

    # 자원 해제
    cap.release()
    cv2.destroyAllWindows()
    # Mac 환경 등에서 창이 안 닫히는 버그 방지
    for _ in range(4):
        cv2.waitKey(1)