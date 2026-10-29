"""환경변수로 바꿀 수 있는 API 설정."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)

from feedback.pipeline import DEFAULT_POSE_MODEL, DEFAULT_YOLO_WEIGHTS
from feedback.reference import DEFAULT_TEMPLATE_PATH


@dataclass(frozen=True)
class Settings:
    # Existing team accounts and analyses remain in public. Staging can select
    # one isolated schema explicitly; no account copying or fallback is used.
    database_schema: str = os.getenv("SWING_DATABASE_SCHEMA") or "public"
    cors_origins: tuple[str, ...] = tuple(
        value.strip() for value in os.getenv("SWING_CORS_ORIGINS", "*").split(",") if value.strip()
    )
    storage_backend: str = os.getenv("SWING_STORAGE_BACKEND", "supabase")
    local_storage_root: str = os.getenv("SWING_LOCAL_STORAGE_ROOT", "")
    session_ttl_seconds: int = int(os.getenv("SWING_SESSION_TTL_SECONDS", "28800"))
    template_path: Path = Path(os.getenv("SWING_TEMPLATE_PATH", DEFAULT_TEMPLATE_PATH))
    yolo_weights: Path = Path(os.getenv("SWING_YOLO_WEIGHTS", DEFAULT_YOLO_WEIGHTS))
    pose_model: Path = Path(os.getenv("SWING_POSE_MODEL", DEFAULT_POSE_MODEL))
    # 기준 템플릿을 만든 영상의 fps. 사용자 영상은 이 fps 로 변환해서 비교한다.
    reference_fps: float = float(os.getenv("SWING_REFERENCE_FPS", "30"))
    max_upload_mb: int = int(os.getenv("SWING_MAX_UPLOAD_MB", "200"))
    database_url: str = field(default=os.getenv("DATABASE_URL", ""), repr=False)
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_role_key: str = field(default=os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""), repr=False)
    storage_bucket: str = os.getenv("SUPABASE_STORAGE_BUCKET", "")
    signed_url_seconds: int = int(os.getenv("SUPABASE_SIGNED_URL_SECONDS", "900"))
    # 같은 DB를 쓰는 팀원들의 작업을 구분한다. 빈 값이면 호스트명 사용.
    worker_id: str = os.getenv("SWING_WORKER_ID") or socket.gethostname()
    # SWING_MOCK=1 이면 모델을 불러오지 않고 고정된 샘플 응답을 돌려준다 (프론트/백엔드 개발용)
    mock: bool = os.getenv("SWING_MOCK", "") == "1"
    # LLM(Gemini) 코칭 문장 생성. 키가 없으면 규칙 기반 폴백을 쓴다.
    gemini_api_key: str = field(default=os.getenv("GEMINI_API_KEY", ""), repr=False)
    # gemini-flash-lite-latest: 코칭 생성은 짧은 JSON 이라 lite 로 충분하다.
    # flash(-latest)는 내부 추론 때문에 45~90초가 걸려 504 가 잦지만, lite 는 ~7초로 끝난다.
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
    # 코칭 범위: 'overall'(종합+부위) 또는 'full'(관절·구간까지). 기본은 overall.
    # 유료 등급 전환 후 GEMINI_COACHING_SCOPE=full 로 켜면 관절/구간 서술도 생성된다.
    coaching_scope: str = os.getenv("GEMINI_COACHING_SCOPE", "overall")


settings = Settings()
