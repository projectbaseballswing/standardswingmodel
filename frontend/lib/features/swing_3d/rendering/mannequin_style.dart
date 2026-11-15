/// Shared sRGB palette for sample, user and raw/P0/final comparisons.
/// Mesh thickness, geometry, coordinate policies and camera remain unchanged.
abstract final class MannequinStyle {
  // compare3d 뷰어와 동일한 균일 회색 룩(중간 회색 배경 + 밝은 회색 몸, 중립 조명).
  // 의미별 색(방향/경고/얼굴마커)을 모두 몸 색으로 통일해 균일하게 보이게 한다.
  static const background = 0x222C3A;
  static const body = 0xD6D6D6;
  static const head = 0xD6D6D6;
  static const direction = 0xD6D6D6;
  static const inactive = 0xD6D6D6;
  static const faceDetail = 0xD6D6D6;
  static const backDetail = 0xD6D6D6;
  static const ghost = 0xA4B7BF;
  static const grid = 0x8A8A8A;
  // 청록 틴트 제거 → 중립 흰/회색 조명.
  static const skyLight = 0xFFFFFF;
  static const groundLight = 0x9A9A9A;
  static const keyLight = 0xFFFFFF;
  static const rimLight = 0xB4B4B4;
  static const fillLight = 0xC8C8C8;
}
