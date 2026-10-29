/// Opt-in verification telemetry only; no production player or data API.
library;

import 'scene_diagnostics_stub.dart'
    if (dart.library.js_interop) 'scene_diagnostics_web.dart'
    as platform;

const sceneDiagnosticsEnabled = bool.fromEnvironment('SWING_3D_DIAGNOSTICS');

void publishSceneDiagnostics(Map<String, dynamic> state) {
  if (sceneDiagnosticsEnabled) platform.publish(state);
}

void clearSceneDiagnostics() {
  if (sceneDiagnosticsEnabled) platform.clear();
}
