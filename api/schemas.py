"""API 요청/응답 스키마. 필드 이름과 단위를 고정해서 이후 LLM 피드백 입력으로도 그대로 쓴다."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Level = Literal["good", "caution", "warning"]
# 값을 얼마나 믿을 수 있는지. 영상 품질과 기준 데이터 표본 수로 정한다.
Reliability = Literal["high", "medium", "low"]
Direction = Literal["similar", "higher", "lower"]
JobStatus = Literal["queued", "processing", "done", "failed"]


# ----------------------------------------------------------------------
# 공통
# ----------------------------------------------------------------------
class Quality(BaseModel):
    source_fps: Optional[float] = None
    feature_fps: Optional[float] = None
    n_frames: Optional[int] = None
    impact_frame_in_video: Optional[int] = None
    pad_left_frames: int = Field(0, description="임팩트 전 60프레임을 채우려고 반복한 프레임 수")
    pad_right_frames: int = Field(0, description="임팩트 후 20프레임을 채우려고 반복한 프레임 수")
    max_missing_gap: Optional[int] = Field(None, description="타자 bbox 최대 연속 결측 프레임 수")
    nan_ratio: Optional[float] = None
    joint_visibility: Dict[str, float] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


# ----------------------------------------------------------------------
# 종합 피드백
# ----------------------------------------------------------------------
class GroupScore(BaseModel):
    key: str
    name: str
    distance: float
    score: float


class WorstSegment(BaseModel):
    start_frame: int
    end_frame: int
    phase: str
    distance: float


class Issue(BaseModel):
    type: Literal["joint_angle"]
    joint: str
    joint_name: str
    phase: str
    phase_name: str
    user: float
    reference: float
    diff: float
    z_score: float
    direction: Direction
    level: Level


class OverallFeedback(BaseModel):
    model_version: str = Field(description="비교 모델 버전. 값의 의미가 바뀌면 올라간다")
    available: bool = Field(True, description="이 피드백을 계산할 수 있었는지")
    reliability: Reliability = Field("medium", description="값의 신뢰도")
    score: Optional[float] = Field(None, description="0~100. 프로 선수 스윙이 기준과 보통 떨어진 거리를 80점으로 환산")
    distance: Optional[float] = Field(None, description="기준 템플릿과의 거리")
    typical_pro_distance: Optional[float] = Field(None, description="80점에 해당하는 거리")
    group_scores: List[GroupScore]
    worst_segment: Optional[WorstSegment] = None
    frame_distances: List[float] = Field(description="템플릿 시간축 80프레임별 거리")
    top_issues: List[Issue]
    quality: Quality


# ----------------------------------------------------------------------
# 관절별 피드백
# ----------------------------------------------------------------------
class JointPhaseStat(BaseModel):
    phase: str
    phase_name: str
    user_mean: float
    reference_mean: float
    reference_std: float
    diff: float = Field(description="user_mean - reference_mean (deg)")
    z_score: float = Field(description="기준 템플릿 편차 대비 차이")
    direction: Direction
    level: Level


class JointImpact(BaseModel):
    user: float
    reference: float
    diff: float
    z_score: float
    level: Level


class RangeOfMotion(BaseModel):
    user: float
    reference: float
    diff: float


class JointSeries(BaseModel):
    user: List[float]
    reference: List[float]
    reference_std: List[float]


class JointFeedback(BaseModel):
    key: str
    name: str
    body_part: str
    description: str
    unit: Literal["deg"]
    available: bool = Field(True, description="이 관절을 비교할 수 있었는지")
    reliability: Reliability = "medium"
    level: Level
    worst_phase: str
    impact: Optional[JointImpact] = None
    range_of_motion: Optional[RangeOfMotion] = None
    phases: List[JointPhaseStat]
    series: Optional[JointSeries] = None


class JointsFeedback(BaseModel):
    joints: List[JointFeedback]


# ----------------------------------------------------------------------
# 구간별 피드백
# ----------------------------------------------------------------------
class PhaseDeviation(BaseModel):
    joint: str
    joint_name: str
    diff: float
    z_score: float
    direction: Direction
    level: Level


class PhaseFeedback(BaseModel):
    key: str = Field(description="구간 키. 구간 구성은 모델 버전에 따라 늘어날 수 있다")
    name: str
    available: bool = Field(True, description="이 구간이 영상에 담겨 분석할 수 있었는지")
    reliability: Reliability = "medium"
    unavailable_reason: Optional[str] = Field(None, description="available=false 일 때 이유")
    reference_frames: Optional[List[int]] = Field(None, description="[시작, 끝) 기준 프레임")
    user_frames: Optional[List[int]] = Field(None, description="[시작, 끝) 사용자 프레임")
    reference_duration_ms: Optional[float] = None
    user_duration_ms: Optional[float] = None
    tempo_ratio: Optional[float] = Field(None, description="user/reference. 1보다 크면 기준보다 느림")
    tempo_level: Optional[Level] = None
    distance: Optional[float] = None
    score: Optional[float] = None
    top_deviations: List[PhaseDeviation]
    warnings: List[str]


class Rhythm(BaseModel):
    description: str
    user: Optional[float] = None
    reference: Optional[float] = None


class PhasesFeedback(BaseModel):
    model_version: str
    impact_frame: int
    user_fps: float
    reference_fps: float
    rhythm: Rhythm
    phases: List[PhaseFeedback]


# ----------------------------------------------------------------------
# 속도 (다음 모델 버전에서 값이 채워진다. 지금은 available=false)
# ----------------------------------------------------------------------
class SpeedMetric(BaseModel):
    key: str = Field(description="예: swing_time, peak_hand_speed, hip_rotation_speed")
    name: str
    unit: str
    available: bool = False
    reliability: Reliability = "low"
    user: Optional[float] = None
    reference: Optional[float] = None
    reference_std: Optional[float] = None
    diff: Optional[float] = None
    z_score: Optional[float] = None
    level: Optional[Level] = None


class SpeedFeedback(BaseModel):
    model_version: str
    available: bool = False
    metrics: List[SpeedMetric] = Field(default_factory=list)


# ----------------------------------------------------------------------
# 분석 작업
# ----------------------------------------------------------------------
class AnalysisReport(BaseModel):
    model_version: str
    overall: OverallFeedback
    joints: List[JointFeedback]
    phases: PhasesFeedback
    speed: SpeedFeedback


class AnalysisError(BaseModel):
    code: str
    message: str


class AnalysisCreated(BaseModel):
    analysis_id: str
    status: JobStatus


class Analysis(BaseModel):
    analysis_id: str
    status: JobStatus
    stage: Optional[str] = Field(None, description="처리 중인 단계")
    created_at: datetime
    finished_at: Optional[datetime] = None
    input: Dict[str, object] = Field(default_factory=dict)
    error: Optional[AnalysisError] = None
    result: Optional[AnalysisReport] = None


class Health(BaseModel):
    status: Literal["ok"]
    model_version: str
    mock: bool = Field(False, description="목업 모드 여부. true 면 고정된 샘플 응답을 돌려준다")
    template_path: str
    video_pipeline_loaded: bool
