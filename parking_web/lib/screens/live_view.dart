import 'package:flutter/material.dart';
import 'dart:convert';
import 'dart:async';
import 'dart:typed_data';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import '../config/api.dart';
import '../config/session.dart';
import '../config/theme_controller.dart';

class LiveViewScreen extends StatefulWidget {
  final int cameraId;
  final String ip;
  final String name;
  const LiveViewScreen({super.key, required this.cameraId, required this.ip, required this.name});

  @override
  State<LiveViewScreen> createState() => _LiveViewScreenState();
}

class _LiveViewScreenState extends State<LiveViewScreen> {
  WebSocketChannel? _channel;
  Uint8List? _currentImage;
  bool _isConnected = false;
  bool _isFullScreen = false;
  bool _isSavingHistory = false;
  int _retryCount = 0;
  static const int _maxRetries = 5;
  late final String _serverUrl;

  @override
  void initState() {
    super.initState();
    _serverUrl = _buildWebSocketUrl();
    _connectWebSocket();
  }

  String _buildWebSocketUrl() {
    final baseUri = Uri.parse(BASE_URL);
    final wsScheme = baseUri.scheme == 'https' ? 'wss' : 'ws';
    final wsUri = baseUri.replace(scheme: wsScheme, path: '/ws/live');
    final serverUrl = wsUri.toString();
    print('Using server URL: $serverUrl');
    return serverUrl;
  }

  void _connectWebSocket() {
    try {
      _channel = WebSocketChannel.connect(
        Uri.parse(_serverUrl),
      );

      // ส่ง camera data
      _channel!.sink.add(jsonEncode({
        'camera_id': widget.cameraId,
      }));

      // รับ binary frames
      _channel!.stream.listen(
        (data) {
          if (data is Uint8List) {
            setState(() {
              _currentImage = data;
              _isConnected = true;
              _retryCount = 0;
            });
          }
        },
        onError: (error) {
          print('WebSocket error: $error');
          _handleError();
        },
        onDone: () {
          print('WebSocket closed');
          _handleError();
        },
      );
    } catch (e) {
      print('WebSocket connect error: $e');
      _handleError();
    }
  }

  void _handleError() {
    _retryCount++;
    if (_retryCount >= _maxRetries && _isConnected) {
      setState(() => _isConnected = false);
    }
    // Retry after delay
    Future.delayed(Duration(seconds: 2), () {
      if (mounted && _retryCount < _maxRetries) {
        _connectWebSocket();
      }
    });
  }

  Future<void> _markParkingSuccess() async {
    setState(() {
      _isSavingHistory = true;
    });

    try {
      final username = await SessionStore.getUsername();
      if ((username ?? '').isEmpty) {
        throw Exception('ไม่พบข้อมูลผู้ใช้ในระบบ');
      }
      final response = await http.post(
        buildApiUri('/parking_history/log'),
        headers: buildApiHeaders(jsonBody: true),
        body: jsonEncode({
          'username': username,
          'camera_id': widget.cameraId,
          'event_type': 'parking_success',
        }),
      );

      if (response.statusCode == 200) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('บันทึกประวัติการจอดเรียบร้อย'),
            backgroundColor: Colors.green,
            duration: Duration(seconds: 2),
          ),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('เกิดข้อผิดพลาดในการบันทึก'),
            backgroundColor: Colors.red,
          ),
        );
      }
    } catch (e) {
      print('Error marking parking success: $e');
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('ข้อผิดพลาด: ${e.toString()}'),
          backgroundColor: Colors.red,
        ),
      );
    } finally {
      setState(() {
        _isSavingHistory = false;
      });
    }
  }

  @override
  void dispose() {
    _channel?.sink.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: _isFullScreen
          ? null
          : AppBar(
              title: Text("ภาพสด: ${widget.name}"),
              centerTitle: true,
              actions: const [ThemeModeToggleButton()],
            ),
      body: Stack(
        children: [
          Padding(
            padding: EdgeInsets.all(_isFullScreen ? 0 : 16),
            child: Column(
              children: [
                if (!_isFullScreen)
                  Card(
                    elevation: 4,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Padding(
                      padding: EdgeInsets.all(16),
                      child: Row(
                        children: [
                          Icon(Icons.videocam, color: Theme.of(context).primaryColor),
                          SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  widget.name,
                                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                                Text(
                                  'IP: ${widget.ip}',
                                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                                    color: Colors.grey[600],
                                  ),
                                ),
                              ],
                            ),
                          ),
                          Container(
                            padding: EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                            decoration: BoxDecoration(
                              color: _getStatusColor(),
                              borderRadius: BorderRadius.circular(16),
                            ),
                            child: Text(
                              _getStatusText(),
                              style: TextStyle(
                                color: Colors.white,
                                fontSize: 12,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                if (!_isFullScreen) SizedBox(height: 16),
                Expanded(
                  child: Card(
                    elevation: _isFullScreen ? 0 : 4,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(_isFullScreen ? 0 : 12),
                    ),
                    child: Container(
                      width: double.infinity,
                      color: Colors.black,
                      child: _currentImage != null
                          ? ClipRRect(
                              borderRadius: BorderRadius.circular(_isFullScreen ? 0 : 12),
                              child: Image.memory(
                                _currentImage!,
                                fit: BoxFit.contain,
                                gaplessPlayback: true,
                              ),
                            )
                          : Center(
                              child: Column(
                                mainAxisAlignment: MainAxisAlignment.center,
                                children: [
                                  CircularProgressIndicator(),
                                  SizedBox(height: 16),
                                  Text(
                                    _isConnected ? 'กำลังโหลดภาพ...' : 'รอการเชื่อมต่อ...',
                                    style: Theme.of(context).textTheme.bodyLarge?.copyWith(color: Colors.white),
                                  ),
                                ],
                              ),
                            ),
                    ),
                  ),
                ),
                if (!_isFullScreen) SizedBox(height: 16),
                if (!_isFullScreen)
                  ElevatedButton.icon(
                    onPressed: _isSavingHistory ? null : _markParkingSuccess,
                    icon: _isSavingHistory
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.check_circle),
                    label: Text(_isSavingHistory ? 'กำลังบันทึก...' : 'เข้าจอดสำเร็จ'),
                    style: ElevatedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 24),
                      backgroundColor: Colors.green,
                      foregroundColor: Colors.white,
                    ),
                  ),
              ],
            ),
          ),
          SafeArea(
            child: Align(
              alignment: Alignment.topRight,
              child: Padding(
                padding: const EdgeInsets.all(12.0),
                child: Material(
                  color: Colors.black54,
                  borderRadius: BorderRadius.circular(24),
                  child: IconButton(
                    tooltip: _isFullScreen ? 'ออกจากเต็มจอ' : 'เต็มจอ',
                    icon: Icon(
                      _isFullScreen ? Icons.fullscreen_exit : Icons.fullscreen,
                      color: Colors.white,
                    ),
                    onPressed: () {
                      setState(() {
                        _isFullScreen = !_isFullScreen;
                      });
                    },
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Color _getStatusColor() {
    return _isConnected ? Colors.green : (_retryCount > 0 ? Colors.orange : Colors.grey);
  }

  String _getStatusText() {
    if (_isConnected) return 'เชื่อมต่อแล้ว';
    if (_retryCount > 0) return 'กำลังเชื่อมต่อ...';
    return 'กำลังโหลด...';
  }
}