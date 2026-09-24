"""API 요청/응답 스키마. 필드 이름과 단위를 고정해서 이후 LLM 피드백 입력으로도 그대로 쓴다."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Level = Literal["good", "caution", "warning"]
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
    score: float = Field(description="0~100. 프로 선수 스윙이 기준과 보통 떨어진 거리를 80점으로 환산")
    distance: float = Field(description="기준 템플릿과의 DTW 거리 (scaled 단위)")
    typical_pro_distance: float = Field(description="80점에 해당하는 거리")
    group_scores: List[GroupScore]
    worst_segment: WorstSegment
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
    level: Level
    worst_phase: str
    impact: JointImpact
    range_of_motion: RangeOfMotion
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
    key: str
    name: str
    reference_frames: List[int] = Field(description="[시작, 끝) 템플릿 프레임")
    user_frames: List[int] = Field(description="[시작, 끝) 사용자 프레임 (DTW 경로 기준)")
    reference_duration_ms: float
    user_duration_ms: float
    tempo_ratio: float = Field(description="user_duration_ms / reference_duration_ms. 1보다 크면 기준보다 느림")
    tempo_level: Level
    distance: float
    score: float
    top_deviations: List[PhaseDeviation]
    warnings: List[str]


class Rhythm(BaseModel):
    description: str
    user: float
    reference: float


class PhasesFeedback(BaseModel):
    impact_frame: int
    user_fps: float
    reference_fps: float
    rhythm: Rhythm
    phases: List[PhaseFeedback]


# ----------------------------------------------------------------------
# 분석 작업
# ----------------------------------------------------------------------
class AnalysisReport(BaseModel):
    overall: OverallFeedback
    joints: List[JointFeedback]
    phases: PhasesFeedback


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
    template_path: str
    video_pipeline_loaded: bool
