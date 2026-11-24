/// Interpretation of stored measurements. Future/unknown versions stay unknown.
String? feedbackMeasurementFamily(String? version) {
  if (const {
    '0.2',
    '0.2-draft',
    '0.2.1',
    '0.2.1-draft',
    '0.2.2',
    '0.2.2-draft',
  }.contains(version)) {
    return 'shoulder-width-v1';
  }
  if (const {'0.2.3', '0.2.3-draft'}.contains(version)) return 'torso-leg-v2';
  return null;
}

String? feedbackNormalizedDefinition(String key, String? version) {
  final family = feedbackMeasurementFamily(version);
  final relative = const {
    'hand_x_from_shoulder': '양 손목 중심과 양 어깨 중심의 화면상 앞뒤 상대 위치',
    'hand_y_from_shoulder': '양 손목 중심과 양 어깨 중심의 화면상 상대 높이',
    'shoulder_x_from_hip': '양 어깨 중심과 골반 중심의 화면상 앞뒤 상대 위치',
    'shoulder_y_from_hip': '양 어깨 중심과 골반 중심의 화면상 상대 높이',
    'lead_ankle_x_from_hip': '앞발목과 골반 중심의 화면상 앞뒤 상대 위치',
  }[key];
  if (relative != null) {
    if (family == null) {
      return '$relative예요. 저장된 모델의 정규화 기준을 확인할 수 없어 최신 단위를 적용하지 않아요.'
          '${key == 'lead_ankle_x_from_hip' ? ' 실제 보폭·스탠스 폭·이동 거리가 아니에요.' : ''}';
    }
    final scale = family == 'torso-leg-v2' && key != 'lead_ankle_x_from_hip'
        ? '몸통 길이'
        : '어깨너비';
    final limit = key == 'lead_ankle_x_from_hip'
        ? '실제 보폭·스탠스 폭·이동 거리가 아니에요.'
        : '실제 거리(cm)를 나타내지는 않아요.';
    return '$relative를 $scale 기준으로 정규화한 값이에요. $limit';
  }
  if (key == 'lead_ankle_y_from_hip') {
    if (family == 'torso-leg-v2') {
      return '뒷발목을 바닥 기준으로 삼은 앞발목의 화면상 상대 높이예요. 양쪽 다리 길이 평균의 중앙값으로 정규화하며, 실제 바닥 높이나 체형·촬영 구도의 영향이 없어졌다는 뜻은 아니에요.';
    }
    if (family == 'shoulder-width-v1') {
      return '골반 중심 기준 앞발목의 화면상 상대 높이를 어깨너비로 정규화한 값이에요. 실제 지면에서 발을 들어 올린 높이는 아니에요.';
    }
    return '저장된 모델에서 앞발 높이의 기준점과 정규화 방식을 확인할 수 없어요. 최신 모델의 뒷발목·다리 길이 기준을 적용하지 않아요.';
  }
  return null;
}

String feedbackReportVersion(Map<String, dynamic> report) {
  final overall = report['overall'];
  final supplied = [
    report['model_version'],
    if (overall is Map) overall['model_version'],
  ].where((v) => v != null).toList();
  if (supplied.isEmpty ||
      supplied.any((v) => v is! String || v.isEmpty) ||
      supplied.toSet().length != 1) {
    return 'unknown';
  }
  return supplied.first as String;
}
