import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// 관절·구간 LLM 코칭이 아직 생성 중(extended_status='pending')일 때 보여주는 안내 줄.
///
/// 종합 피드백은 먼저 떠 있고, 관절·구간 코멘트만 뒤이어 채워진다. 그동안 사용자가
/// "비어 있다"고 오해하지 않도록 작은 스피너와 함께 작성 중임을 알린다.
class CoachingPendingNote extends StatelessWidget {
  const CoachingPendingNote({super.key, required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: AppColors.primary.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          const SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(fontSize: 13, color: AppColors.primary),
            ),
          ),
        ],
      ),
    );
  }
}
