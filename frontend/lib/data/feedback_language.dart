/// Display wording only. Never rewrites stored reports, scores or GPT responses.
String feedbackFeatureName(String key, String fallback) =>
    const {
      'lead_elbow_angle': '앞팔 팔꿈치',
      'rear_elbow_angle': '뒷팔 팔꿈치',
      'lead_knee_angle': '앞무릎',
      'rear_knee_angle': '뒷무릎',
      'hip_tilt': '골반선 기울기',
      'shoulder_tilt': '어깨선 기울기',
      'hand_y_from_shoulder': '어깨 기준 손 높이',
      'hand_x_from_shoulder': '어깨 기준 손의 앞뒤 위치',
      'lead_ankle_x_from_hip': '골반 기준 앞발 위치',
      'lead_ankle_y_from_hip': '골반 기준 앞발 높이',
      'shoulder_x_from_hip': '골반 기준 상체의 앞뒤 위치',
      'shoulder_y_from_hip': '골반 기준 어깨 높이',
      'hip_shoulder_separation': '어깨와 골반의 회전 차이',
    }[key] ??
    fallback;

String feedbackTopic(String value) {
  if (value.isEmpty) return value;
  final code = value.runes.last;
  final finalConsonant =
      code >= 0xac00 && code <= 0xd7a3 && (code - 0xac00) % 28 != 0;
  return '$value${finalConsonant ? '은' : '는'}';
}

String feedbackObservation(
  String key,
  String name,
  String phase,
  String direction,
) {
  // These directions already include the body part and its reference frame.
  final explicitSubject =
      (key == 'hip_tilt' ||
          key == 'shoulder_tilt' ||
          key == 'lead_ankle_x_from_hip') &&
      direction.startsWith('화면에서');
  if (explicitSubject) {
    return '$phase 구간 평균에서는 ${direction.replaceFirst('화면에서 ', '화면상 ')}.';
  }
  return '$phase 구간 평균에서 '
      '${feedbackTopic(feedbackFeatureName(key, name))} $direction.';
}

String feedbackObservationAction(
  String key,
  String name,
  String phase, {
  bool hasReferenceSeries = false,
}) {
  final focus = switch (key) {
    'hip_tilt' =>
      '양쪽 골반을 이은 선과 발 디딤을 함께 보세요. 기울기 자체보다 몸이 흔들려 발을 다시 디디는 등 실제 균형 문제가 보이는지 살펴보세요.',
    'lead_ankle_x_from_hip' =>
      '앞발목과 골반 중심을 함께 따라가 보세요. 앞발이 움직인 것인지, 발을 딛은 뒤 골반이 움직인 것인지 나눠 확인해 보세요.',
    'hand_y_from_shoulder' =>
      '양손의 가운데와 양어깨의 가운데를 함께 따라가 보세요. 손이 움직인 것인지 어깨 높이가 달라진 것인지 나눠 비교해 보세요.',
    'lead_elbow_angle' =>
      '앞쪽 어깨·팔꿈치·손목을 따라가며 팔이 펴지고 굽혀지는 흐름을 보세요. 측정 각도 차이가 커도 교정이 필요하다는 뜻은 아니므로 실제 팔 모양부터 확인하세요.',
    'rear_elbow_angle' =>
      '뒤쪽 어깨·팔꿈치·손목을 따라가며 팔이 펴지고 굽혀지는 흐름을 보세요. 측정 각도 차이가 커도 교정이 필요하다는 뜻은 아니므로 실제 팔 모양부터 확인하세요.',
    _ =>
      '${feedbackFeatureName(key, name)}의 움직임을 살펴보세요. 안내가 준비되지 않은 항목은 위치를 임의로 바꾸지 마세요.',
  };
  final comparison = hasReferenceSeries
      ? '기준과의 수치 차이는 관절별 분석 그래프에서 확인할 수 있어요. 기준 영상은 제공되지 않아 원본에서는 내 움직임을 살펴봐 주세요.'
      : '비교 가능한 기준 그래프나 기준 영상이 없어, 원본만으로 기준 자세와의 차이를 직접 확인할 수는 없어요.';
  return '기존 원본 영상의 $phase 구간을 처음·중간·끝 순서로 천천히 보세요. $focus $comparison';
}

/// A small, optional observation trial, never a diagnosis or a validated training effect.
/// Eligibility permits an invitation, not approval of a correction. Confirmation
/// of actual motion/balance must come from the user watching their existing video.
String? feedbackConditionalPractice(
  String key,
  String phase,
  String direction, {
  required bool eligible,
}) {
  if (!eligible || !const {'higher', 'lower'}.contains(direction)) return null;
  final stage = const {
    'stride': '앞발을 들고 딛는 동안',
    'transition': '앞발을 딛은 뒤 스윙을 시작하기 전까지',
    'swing': '스윙 시작부터 추정 임팩트까지',
    'follow': '추정 임팩트 뒤 마무리하는 동안',
  }[phase];
  if (stage == null) return null;
  const optionalRecording = '원하면 추가 촬영으로 움직임을 비교할 수 있지만, 다시 찍을 필요는 없어요.';
  switch (key) {
    case 'hip_tilt':
      return '원본에서 몸이 흔들려 발을 다시 디디는 등 실제 균형 문제가 확인될 때만, 배트 없이 $stage 동작을 편한 속도로 작게 이어 해보세요. 골반 기울기 수치를 맞추기보다 발을 다시 디뎌야 하는지 살펴보세요. $optionalRecording';
    case 'lead_ankle_x_from_hip':
      final task = phase == 'stride'
          ? '현재 앞발이 출발하는 자리와 딛는 자리를 표시하고, 배트 없이 천천히 앞발을 들었다 딛어 보세요.'
          : '현재 앞발을 딛는 자리를 표시하고, 배트 없이 느린 빈스윙을 해보세요.';
      return '기존 영상에서 앞발과 골반의 움직임을 구분할 수 있고 더 살펴보고 싶다면, $task $stage 발목과 골반 중심이 어떻게 움직이는지 느껴보세요. $optionalRecording';
    case 'hand_y_from_shoulder':
      return '기존 영상에서 손과 어깨의 움직임이 잘 보이고 직접 살펴보고 싶다면, 배트 없이 느린 빈스윙으로 $stage 양손이 지나가는 길을 이어 움직여 보세요. 기준 수치에 맞춰 손을 올리거나 내리지 말고, 어깨와 손이 함께 움직이는 흐름을 살펴보세요. $optionalRecording';
    case 'lead_elbow_angle':
    case 'rear_elbow_angle':
      final arm = key == 'lead_elbow_angle' ? '앞팔' : '뒷팔';
      return '기존 영상에서 실제 팔 모양을 확인할 수 있고 직접 살펴보고 싶다면, 배트 없이 느린 빈스윙으로 $stage $arm 팔꿈치의 펴짐·굽힘을 이어 재현해 보세요. 자연스럽게 펴지는 팔을 멈추거나 측정된 차이만큼 각도를 꺾지 마세요. $optionalRecording';
    default:
      return null;
  }
}

String feedbackMeasurementLimits(String key) {
  final specific = switch (key) {
    'hip_tilt' =>
      '화면상 골반선의 기울기이며 실제 3D 골반 기울기는 아닙니다. 기준에도 기울기가 있으므로 수평으로 고정하지 않습니다.',
    'lead_ankle_x_from_hip' =>
      '앞발목과 골반 중심의 화면상 상대 위치를 어깨너비로 정규화한 값입니다. 실제 보폭·스탠스 폭·이동 거리가 아니며, 바닥 표시는 발을 더 멀리 보내기 위한 목표가 아닙니다.',
    'hand_y_from_shoulder' =>
      '양 손목 중심과 양 어깨 중심의 상대 높이를 어깨너비로 정규화한 값입니다. 한 손의 궤적이나 실제 높이(cm)가 아닙니다.',
    'lead_elbow_angle' || 'rear_elbow_angle' =>
      '어깨·팔꿈치·손목의 IMAGE 좌표와 축소된 추정 깊이로 계산한 각도입니다. 독립적인 실제 3D 측정값은 아닙니다.',
    _ => '해당 측정의 의미는 관절별 상세 설명에서 확인할 수 있습니다.',
  };
  return '$specific 구간 평균은 동작 흐름의 요약이며 한순간의 목표 자세가 아닙니다. '
      '신뢰도 medium/high는 교정의 타당성을 확인했다는 뜻이 아니며, 큰 각도 차이도 원본 확인이 필요합니다. '
      '먼저 확인할 항목은 신뢰도 조건을 통과한 구간별 표준화 차이의 크기로 고릅니다. 구간 가중치를 반영한 점수 영향도 순서나 전문적인 교정 우선순위는 아닙니다. '
      '화면상의 정상적인 움직임과 추정 좌표의 갑작스러운 이동은 구분해서 확인합니다. '
      '조건부 연습은 차이를 확인하기 위한 작은 비교 시도이며 교정 효과가 검증된 처방은 아닙니다. '
      '기준 그래프는 여러 선수의 측정 평균이며 특정 선수의 정답 자세 영상이 아닙니다. '
      '원본에서 내 움직임을 판단할 수 없으면 연습은 보류합니다.';
}

String feedbackFeatureDescription(String key, String fallback) =>
    const {
      'lead_elbow_angle': '앞쪽 어깨·팔꿈치·손목을 연결한 각도예요. 각도가 클수록 팔꿈치가 더 펴진 자세예요.',
      'rear_elbow_angle': '뒤쪽 어깨·팔꿈치·손목을 연결한 각도예요. 각도가 작을수록 팔꿈치가 더 굽혀진 자세예요.',
      'lead_knee_angle': '앞쪽 골반·무릎·발목을 연결한 각도예요. 각도가 클수록 무릎이 더 펴진 자세예요.',
      'rear_knee_angle': '뒤쪽 골반·무릎·발목을 연결한 각도예요. 각도가 작을수록 무릎이 더 굽혀진 자세예요.',
      'torso_lean': '어깨와 골반 중심을 이은 몸통 선의 기울기예요. 양수는 투수 쪽, 음수는 포수 쪽 방향이에요.',
      'shoulder_tilt': '화면에서 양쪽 어깨를 이은 선의 기울기예요. 몸통이 실제로 돌아간 각도와는 달라요.',
      'hip_tilt':
          '화면에서 양쪽 골반을 이은 선의 기울기예요. 실제 3D 골반 기울기나 골반을 수평으로 맞추라는 뜻은 아니에요.',
      'hand_x_from_shoulder': '어깨 중심을 기준으로 손이 투수 쪽에 얼마나 나와 있는지 보는 값이에요.',
      'hand_y_from_shoulder': '어깨를 기준으로 손이 얼마나 높이 있는지 보는 값이에요.',
      'lead_ankle_x_from_hip':
          '화면에서 골반 중심에 대한 앞발의 앞뒤 위치예요. 준비 자세의 스탠스 폭이나 실제로 앞발을 옮긴 거리가 아니에요.',
      'lead_ankle_y_from_hip': '골반을 기준으로 앞발이 얼마나 높이 있는지 보는 값이에요.',
      'shoulder_x_from_hip': '골반을 기준으로 상체가 앞뒤로 얼마나 치우쳤는지 보는 값이에요.',
      'shoulder_y_from_hip': '골반을 기준으로 어깨가 얼마나 높이 있는지 보는 값이에요.',
      'shoulder_turn':
          '어깨가 투수 쪽으로 얼마나 돌아간 것으로 추정되는지 보여줘요. 카메라 방향과 관절 추정 오차의 영향을 받을 수 있어요.',
      'hip_turn': '골반이 투수 쪽으로 얼마나 돌아간 것으로 추정되는지 보여줘요. 실제 타격 힘을 측정한 값은 아니에요.',
      'hip_shoulder_separation':
          '어깨와 골반이 돌아간 각도의 차이예요. 이 값만으로 회전 순서나 타격 힘을 판단할 수는 없어요. 촬영 구도와 관절 추정 오차의 영향을 받을 수 있어요.',
    }[key] ??
    fallback;

/// Known report notices are translated at the presentation boundary only.
String feedbackReportNotice(String raw) {
  if (raw == '일부 관절이 가려져 있습니다.') {
    return '일부 관절의 인식 품질을 확인해 주세요. 이 안내만으로 가림 여부나 원인은 알 수 없어요.';
  }
  final rotation = RegExp(
    r'^착지부터 임팩트까지 (골반|어깨)[이가] (-?\d+(?:\.\d+)?)도 돌아갔어요\.$',
  ).firstMatch(raw);
  if (rotation != null) {
    return '착지부터 추정 임팩트 시점까지 ${rotation[1] == '골반' ? '골반이' : '어깨가'} 약 ${rotation[2]}도 돌아간 것으로 나타났어요.';
  }
  final separation = RegExp(
    r'^앞발이 닿을 때 어깨가 골반보다 (-?\d+(?:\.\d+)?)도 덜 돌아가 꼬임이 있어요\.$',
  ).firstMatch(raw);
  if (separation != null) {
    return '앞발이 닿을 때 어깨가 골반보다 약 ${separation[1]}도 덜 돌아간 것으로 나타났어요.';
  }
  if (raw == '임팩트까지 꼬임이 풀리면서 어깨가 골반을 따라 돌았어요.') {
    return '착지부터 추정 임팩트 시점까지 어깨와 골반의 회전 차이가 달라졌어요. 정확한 회전 순서까지 판단할 수는 없어요.';
  }
  return raw
      .replaceAll('로딩 시작을 찾지 못했습니다.', '스윙 준비 동작이 시작되는 지점을 찾지 못했어요.')
      .replaceAll('영상이 로딩 도중에 시작한 것 같습니다.', '영상이 스윙 준비 동작 중간부터 시작된 것 같아요.')
      .replaceAll(
        'foot_lift 또는 foot_plant 를 영상에서 찾지 못했습니다.',
        '영상에서 앞발을 들거나 바닥에 딛는 시점을 찾지 못했어요.',
      )
      .replaceAll('영상에 담기지 않아 분석하지 못한 구간: 스트라이드', '영상에서 앞발을 옮기는 구간을 확인하지 못했어요.')
      .replaceAll(
        '선수마다 편차가 커서 템포를 판정하지 않았습니다.',
        '기준 선수들의 동작 시간이 서로 달라 이 구간의 템포 판단을 보류했어요.',
      )
      .replaceAll('수치만 참고하세요.', '표시된 측정값은 참고로만 확인해 주세요.')
      .replaceAll(
        '더 높은 fps 로 촬영하면 판정할 수 있습니다.',
        '촬영 FPS만 높여 동작 시간 비교가 가능해진다고 보장할 수는 없어요.',
      )
      .replaceAll('구간이 짧아 템포를 판정하지 않았습니다.', '비교할 구간이 너무 짧아 동작 시간을 판단하기 어려워요.');
}
