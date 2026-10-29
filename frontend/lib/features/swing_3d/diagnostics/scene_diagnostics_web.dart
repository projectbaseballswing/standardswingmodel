import 'dart:js_interop';

@JS('EXP007_FINAL')
external set _state(JSAny? value);

void publish(Map<String, dynamic> state) => _state = state.jsify();
void clear() => _state = null;
