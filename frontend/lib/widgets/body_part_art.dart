import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../models/feedback.dart';

/// 피그마 신체 부위 일러스트(assets/body)의 영역.
enum BodyRegion { leftArm, rightArm, torso, leftLeg, rightLeg }

/// 부위 상태에 따른 일러스트 색조.
enum BodyTone { good, bad, neutral }

/// 서버 부위 이름(예: "왼쪽 팔")으로 일러스트 영역을 찾는다.
/// 좌우를 알 수 없는 팔·다리는 null.
BodyRegion? bodyRegionOf({
  required String key,
  required String label,
  required BodyPart part,
}) {
  if (key == 'torso' || part == BodyPart.torso) return BodyRegion.torso;
  final left = label.contains('왼');
  if (!left && !label.contains('오른')) return null;
  return part == BodyPart.arm
      ? (left ? BodyRegion.leftArm : BodyRegion.rightArm)
      : (left ? BodyRegion.leftLeg : BodyRegion.rightLeg);
}

/// 피그마 색: 일러스트 색과 46px 썸네일 배경색.
Color bodyToneColor(BodyTone tone) => switch (tone) {
  BodyTone.good => const Color(0xFF4CC38A),
  BodyTone.bad => const Color(0xFFFF6B6B),
  BodyTone.neutral => const Color(0xFFC9CDD3),
};

Color bodyToneSoft(BodyTone tone) => switch (tone) {
  BodyTone.good => const Color(0xFFE8F6EE),
  BodyTone.bad => const Color(0xFFFFECEC),
  BodyTone.neutral => const Color(0xFFF0F0F2),
};

String _regionName(BodyRegion region) => switch (region) {
  BodyRegion.leftArm => 'left_arm',
  BodyRegion.rightArm => 'right_arm',
  BodyRegion.torso => 'torso',
  BodyRegion.leftLeg => 'left_leg',
  BodyRegion.rightLeg => 'right_leg',
};

Widget _tinted(String asset, Color color, {double? width, double? height}) {
  return SvgPicture.asset(
    asset,
    width: width,
    height: height,
    colorFilter: ColorFilter.mode(color, BlendMode.srcIn),
  );
}

/// 부위 하나의 아이콘(피그마 18×21 원본). 좌우를 모르면 같은 부위의 한쪽을 쓴다.
class BodyPartGlyph extends StatelessWidget {
  const BodyPartGlyph({
    super.key,
    required this.part,
    required this.region,
    required this.color,
    this.width = 18,
    this.height = 21,
  });

  final BodyPart part;
  final BodyRegion? region;
  final Color color;
  final double width;
  final double height;

  @override
  Widget build(BuildContext context) {
    final r =
        region ??
        switch (part) {
          BodyPart.arm => BodyRegion.rightArm,
          BodyPart.leg => BodyRegion.leftLeg,
          BodyPart.torso => BodyRegion.torso,
        };
    return _tinted(
      'assets/body/icon_${_regionName(r)}.svg',
      color,
      width: width,
      height: height,
    );
  }
}

/// 종합 피드백 항목의 46px 부위 썸네일: 연한 배경 + 부위 아이콘.
class BodyPartThumb extends StatelessWidget {
  const BodyPartThumb({
    super.key,
    required this.part,
    required this.region,
    required this.tone,
  });

  final BodyPart part;
  final BodyRegion? region;
  final BodyTone tone;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 46,
      height: 46,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: bodyToneSoft(tone),
        borderRadius: BorderRadius.circular(10),
      ),
      // 피그마 썸네일은 18×21 아이콘을 2배로 키운 모양이다.
      child: BodyPartGlyph(
        part: part,
        region: region,
        color: bodyToneColor(tone),
        width: 36,
        height: 42,
      ),
    );
  }
}

/// 관절별 분석의 정면 인체 그림. 피그마 120×186 프레임 기준 비율로 배치한다.
class BodyMap extends StatelessWidget {
  const BodyMap({super.key, required this.colors});

  /// 영역별 색. 없는 영역은 기본 회색.
  final Map<BodyRegion, Color> colors;

  static const _width = 120.0;
  static const _height = 186.0;

  // 피그마 inset(%): 위, 오른쪽, 아래, 왼쪽.
  static const _layout = <String, List<double>>{
    'head': [8.31, 42.03, 78.1, 42],
    'torso': [21.45, 36.88, 43.41, 36.85],
    'left_arm': [25.25, 62.43, 39.99, 14.35],
    'right_arm': [25.25, 14.38, 39.99, 62.41],
    'left_leg': [51.52, 51.12, 4.12, 28.75],
    'right_leg': [51.52, 28.78, 4.12, 51.09],
  };

  Color _colorOf(String name) {
    for (final r in BodyRegion.values) {
      if (_regionName(r) == name) {
        return colors[r] ?? bodyToneColor(BodyTone.neutral);
      }
    }
    return bodyToneColor(BodyTone.neutral);
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: _width,
      height: _height,
      child: Stack(
        children: [
          for (final entry in _layout.entries)
            Positioned(
              top: _height * entry.value[0] / 100,
              right: _width * entry.value[1] / 100,
              bottom: _height * entry.value[2] / 100,
              left: _width * entry.value[3] / 100,
              child: SvgPicture.asset(
                'assets/body/map_${entry.key}.svg',
                fit: BoxFit.fill,
                colorFilter: ColorFilter.mode(
                  _colorOf(entry.key),
                  BlendMode.srcIn,
                ),
              ),
            ),
        ],
      ),
    );
  }
}
