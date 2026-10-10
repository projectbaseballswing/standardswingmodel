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
    key: str = Field(description="lead_arm / rear_arm / torso / lead_leg / rear_leg")
    name: str = Field(description="화면 표시용 이름. 좌우타에 맞춰 좌/우로 변환됨")
    available: bool = True
    reliability: Reliability = Field("medium", description="피처가 하나뿐이거나 검출이 불안정한 부위는 낮다")
    feature_count: int = Field(0, description="이 부위를 이루는 피처 수")
    distance: Optional[float] = None
    score: Optional[float] = None


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
    user: Optional[float] = None
    reference: Optional[float] = None
    diff: Optional[float] = None
    z_score: Optional[float] = None
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
    frame_distances: List[Optional[float]] = Field(
        description="기준 시간축 지점별 거리. 0.1 은 80프레임, 0.2 는 구간 4개 × 20등분")
    top_issues: List[Issue] = Field(default_factory=list, description="기준과 가장 많이 벌어진 항목")
    top_strengths: List[Issue] = Field(default_factory=list, description="기준에 가장 가까운 항목")
    quality: Quality


# ----------------------------------------------------------------------
# 관절별 피드백
# ----------------------------------------------------------------------
class JointPhaseStat(BaseModel):
    phase: str
    phase_name: str
    available: bool = Field(True, description="이 구간이 영상에 담겨 비교할 수 있었는지")
    user_mean: Optional[float] = None
    reference_mean: Optional[float] = None
    reference_std: Optional[float] = None
    diff: Optional[float] = Field(None, description="user_mean - reference_mean")
    z_score: Optional[float] = Field(None, description="기준 스윙들의 편차 대비 차이")
    direction: Direction
    level: Level


class JointImpact(BaseModel):
    user: Optional[float] = None
    reference: Optional[float] = None
    diff: Optional[float] = None
    z_score: Optional[float] = None
    level: Level


class RangeOfMotion(BaseModel):
    user: Optional[float] = None
    reference: Optional[float] = None
    diff: Optional[float] = None


class JointSeries(BaseModel):
    user: List[Optional[float]]
    reference: List[Optional[float]]
    reference_std: List[Optional[float]]


class JointFeedback(BaseModel):
    key: str
    name: str
    body_part: str = Field(description="lead_arm / rear_arm / torso / lead_leg / rear_leg")
    body_part_name: str = Field("", description="화면 표시용 부위 이름. 좌우타에 맞춰 좌/우로 변환됨")
    description: str
    unit: str = Field(description="deg(각도) 또는 body(몸 크기 대비 길이)")
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
    diff: Optional[float] = None
    z_score: Optional[float] = None
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
    events: Dict[str, object] = Field(
        default_factory=dict,
        description="이벤트별 프레임과 임팩트 기준 시점(ms). 0.2 부터 제공",
    )


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
    user_id: Optional[str] = None
    recorded_at: Optional[datetime] = None
    status: JobStatus
    stage: Optional[str] = Field(None, description="처리 중인 단계")
    created_at: datetime
    finished_at: Optional[datetime] = None
    input: Dict[str, object] = Field(default_factory=dict)
    error: Optional[AnalysisError] = None
    result: Optional[AnalysisReport] = None


class SwingListItem(BaseModel):
    analysis_id: str
    recorded_at: datetime = Field(description="표시 시각. 촬영 시각이 없으면 서버에 등록된 시각을 사용")
    status: JobStatus
    score: Optional[float] = Field(None, description="분석이 done인 경우의 종합 점수. 미완료/실패/미제공이면 null")
    thumbnail_url: Optional[str] = Field(None, description="썸네일 미구현: 현재 null")


class SwingListResponse(BaseModel):
    user_id: str
    year_month: Optional[str] = Field(None, description="요청한 YYYY-MM. 전체 조회 시 null")
    count: int
    items: List[SwingListItem]


class VideoURL(BaseModel):
    analysis_id: str
    url: str
    expires_in: int = Field(description="발급 시점 기준 유효기간(초). 만료 시 다시 조회")


class Health(BaseModel):
    status: Literal["ok"]
    model_version: str
    mock: bool = Field(False, description="목업 모드 여부. true 면 고정된 샘플 응답을 돌려준다")
    template_path: str
    video_pipeline_loaded: bool
