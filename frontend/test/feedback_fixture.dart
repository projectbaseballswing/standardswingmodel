/// Mock HTTP로 저장된 결과를 재현한다. 영상/Supabase 요청은 하지 않는다.
Map<String, dynamic> storedAnalysis() => {
  'analysis_id': 'saved-analysis',
  'status': 'done',
  'recorded_at': '2026-10-09T09:30:00Z',
  'created_at': '2026-10-10T01:00:00Z',
  'finished_at': '2026-10-10T01:01:00Z',
  'result': <String, dynamic>{
    'overall': <String, dynamic>{
      'score': 77.3,
      'group_scores': [
        <String, dynamic>{
          'key': 'lead_arm',
          'name': '왼쪽 팔',
          'available': true,
          'score': 63.8,
          'reliability': 'high',
        },
      ],
    },
    'joints': [
      {
        'key': 'lead_elbow_angle',
        'name': '앞팔 팔꿈치 각도',
        'body_part': 'lead_arm',
        'available': true,
        'reliability': 'high',
        'level': 'caution',
        'description': '실제 팔꿈치 분석',
        'unit': 'deg',
        'worst_phase': 'swing',
        'impact': {'user': 123.4, 'reference': 111.2, 'diff': 12.2},
        'range_of_motion': {'user': 20.5, 'reference': 18.0, 'diff': 2.5},
        'series': {
          'user': [110.0, null, 123.4],
          'reference': [105.0, 108.0, 111.2],
          'reference_std': [3.0, 4.0, 5.0],
        },
        'phases': [
          {'phase': 'swing', 'direction': 'higher', 'z_score': 1.0},
        ],
      },
    ],
  },
};
