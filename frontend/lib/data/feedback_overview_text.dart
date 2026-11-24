import '../models/feedback.dart';
import 'feedback_language.dart';

/// Short overview wording only. Eligibility, ranking and measurements continue
/// to come from FeedbackEvidence; the full explanation stays in disclosure.
String overviewVideoCheck(FeedbackEvidence evidence) =>
    switch (evidence.joint) {
      'hip_tilt' || 'lead_ankle_x_from_hip' => feedbackPositionVideoCheck(
        evidence.joint,
        evidence.phase,
      ),
      'hand_y_from_shoulder' => '양손과 양어깨의 가운데를 따라가며, 손과 어깨 중 어느 쪽이 움직이는지 보세요.',
      'lead_elbow_angle' => '어깨·팔꿈치·손목을 따라 앞팔의 펴짐·굽힘을 확인해요. 각도 차이만으로 교정하지 않아요.',
      'rear_elbow_angle' => '어깨·팔꿈치·손목을 따라 뒷팔의 펴짐·굽힘을 확인해요. 각도 차이만으로 교정하지 않아요.',
      _ => '${evidence.name}의 움직임을 원본에서 확인해요. 차이만 보고 자세를 바꾸지는 마세요.',
    };

String? overviewOptionalPractice(FeedbackEvidence evidence) {
  // Reuse the established gate, including missing-data/quality/feature checks.
  if (evidence.practice == null) return null;
  final stage = evidence.phaseName;
  return switch (evidence.joint) {
    'hip_tilt' =>
      '영상에서 실제 균형 문제가 확인될 때만, 배트 없이 $stage 동작을 작고 천천히 해보세요. 골반을 수평으로 맞추지는 마세요.',
    'lead_ankle_x_from_hip' =>
      '영상에서 발과 골반 움직임을 구분할 수 있다면, 현재 발 디딤을 표시하고 $stage 동작을 배트 없이 천천히 재현해요. 보폭을 넓히려는 연습은 아니에요.',
    'hand_y_from_shoulder' =>
      '영상에서 손과 어깨가 잘 보이면, 배트 없이 $stage의 손 움직임을 천천히 재현해요. 기준 수치에 맞춰 손을 올리거나 내리지는 마세요.',
    'lead_elbow_angle' || 'rear_elbow_angle' =>
      '영상에서 실제 팔 모양을 확인한 경우에만, 배트 없이 $stage의 펴짐·굽힘을 천천히 재현해요. 측정된 차이만큼 각도를 꺾지는 마세요.',
    _ => null,
  };
}
