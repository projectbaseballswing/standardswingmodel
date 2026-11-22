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
      'lead_ankle_y_from_hip': '앞발 높이',
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

String feedbackObservationAction(String key, String name, String phase) =>
    '원본 영상의 $phase 구간에서 ${feedbackFeatureName(key, name)}에 같은 차이가 보이는지 확인해 보세요. '
    '관절이 가려졌다면 측정이 달라질 수 있어요.';

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
      'lead_ankle_y_from_hip':
          '뒷발을 바닥 기준으로 삼아 앞발이 얼마나 높이 들렸는지 보는 값이에요. 다리 길이 대비로 재서 키나 체형과는 무관해요.',
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
