// Default to local backend for development. Override with
// --dart-define=PARKING_API_BASE_URL=https://your-ngrok-url
const String _RAW_BASE_URL = String.fromEnvironment(
  'PARKING_API_BASE_URL',
  defaultValue: 'http://127.0.0.1:8000',
);

final String BASE_URL = _RAW_BASE_URL.replaceFirst(RegExp(r'/+$'), '');

Map<String, String> buildApiHeaders({bool jsonBody = false}) {
  final headers = <String, String>{
    'Accept': 'application/json',
  };

  if (BASE_URL.contains('ngrok-free.dev')) {
    headers['ngrok-skip-browser-warning'] = 'true';
  }

  if (jsonBody) {
    headers['Content-Type'] = 'application/json';
  }

  return headers;
}

Uri buildApiUri(String path, {Map<String, dynamic>? queryParameters}) {
  final baseUri = Uri.parse(BASE_URL);
  final normalizedPath = path.startsWith('/') ? path : '/$path';
  final normalizedQuery = queryParameters == null
      ? null
      : queryParameters.map(
          (key, value) => MapEntry(key, value?.toString() ?? ''),
        );

  return baseUri.replace(
    path: normalizedPath,
    queryParameters: normalizedQuery,
  );
}
