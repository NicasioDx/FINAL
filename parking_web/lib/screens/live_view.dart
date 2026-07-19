import 'package:flutter/material.dart';
import 'dart:convert';
import 'dart:async';
import 'dart:typed_data';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:url_launcher/url_launcher.dart';
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
  bool _isAdmin = false;
  bool _showManualRoiPopup = false;
  String? _streamError;
  int _retryCount = 0;
  static const int _maxRetries = 5;
  late final String _serverUrl;
  final TextEditingController _roiSecondController = TextEditingController(text: '50');

  @override
  void initState() {
    super.initState();
    _serverUrl = _buildWebSocketUrl();
    _loadRole();
    _connectWebSocket();
  }

  Future<void> _loadRole() async {
    final role = await SessionStore.getRole();
    if (mounted) {
      setState(() {
        _isAdmin = role == 'admin';
        if (!_isAdmin) {
          _showManualRoiPopup = false;
        }
      });
    }
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
      _channel?.sink.close();
      _channel = WebSocketChannel.connect(
        Uri.parse(_serverUrl),
      );
      print('Opening live stream camera_id=${widget.cameraId}');

      // ส่ง camera data
      _channel!.sink.add(jsonEncode({
        'camera_id': widget.cameraId,
      }));

      // รับ binary frames
      _channel!.stream.listen(
        (data) {
          if (data is String) {
            print('WebSocket message: $data');
            setState(() {
              _streamError = data;
              _isConnected = false;
            });
            return;
          }

          Uint8List? bytes;
          if (data is Uint8List) {
            bytes = data;
          } else if (data is ByteBuffer) {
            bytes = data.asUint8List();
          } else if (data is List<int>) {
            bytes = Uint8List.fromList(data);
          }

          if (bytes != null) {
            setState(() {
              _currentImage = bytes;
              _streamError = null;
              _isConnected = true;
              _retryCount = 0;
            });
          } else {
            print('Unsupported WebSocket data type: ${data.runtimeType}');
          }
        },
        onError: (error) {
          print('WebSocket error: $error');
          _handleError(error.toString());
        },
        onDone: () {
          print('WebSocket closed');
          _handleError('WebSocket closed');
        },
      );
    } catch (e) {
      print('WebSocket connect error: $e');
      _handleError(e.toString());
    }
  }

  void _handleError([String? message]) {
    _retryCount++;
    if (mounted) {
      setState(() {
        _isConnected = false;
        if (_currentImage == null) {
          _streamError = message;
        }
      });
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
      final slotNumber = await _selectLatestOccupiedSlot();
      if (slotNumber == null) {
        return;
      }
      final response = await http.post(
        buildApiUri('/parking_history/log'),
        headers: buildApiHeaders(jsonBody: true),
        body: jsonEncode({
          'username': username,
          'camera_id': widget.cameraId,
          'event_type': 'parking_success',
          'slot_number': slotNumber,
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

  Future<int?> _selectLatestOccupiedSlot() async {
    final response = await http.get(
      buildApiUri('/parking_status/latest', queryParameters: {
        'camera_id': widget.cameraId.toString(),
      }),
      headers: buildApiHeaders(),
    );

    if (response.statusCode != 200) {
      throw Exception('Cannot load occupied parking slots');
    }

    final body = jsonDecode(response.body);
    final slots = (body['slots'] as List<dynamic>? ?? [])
        .where((slot) => slot['manual_logged'] != true)
        .toList();

    if (slots.isEmpty) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('ยังไม่พบช่องที่มีรถจอดล่าสุด'),
            backgroundColor: Colors.orange,
          ),
        );
      }
      return null;
    }

    if (!mounted) return null;
    return showDialog<int>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: const Text('เลือกช่องที่รถจอดล่าสุด'),
          content: SizedBox(
            width: 320,
            child: ListView.separated(
              shrinkWrap: true,
              itemCount: slots.length,
              separatorBuilder: (_, __) => const Divider(height: 1),
              itemBuilder: (context, index) {
                final slot = slots[index];
                final slotNumber = int.tryParse(slot['slot_number'].toString()) ?? 0;
                final seconds = (slot['occupied_seconds'] as num?)?.round() ?? 0;
                return ListTile(
                  title: Text('ช่อง $slotNumber'),
                  subtitle: Text(index == 0 ? 'รถที่จอดล่าสุด (${seconds}s)' : 'จอดแล้ว ${seconds}s'),
                  onTap: () => Navigator.of(context).pop(slotNumber),
                );
              },
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('ยกเลิก'),
            ),
          ],
        );
      },
    );
  }

  @override
  void dispose() {
    _roiSecondController.dispose();
    _channel?.sink.close();
    super.dispose();
  }

  String _roiMarkerUrl() {
    return buildApiUri(
      '/roi_marker',
      queryParameters: {
        'camera_id': widget.cameraId.toString(),
      },
    ).toString();
  }

  String _roiFrameUrl() {
    final second = double.tryParse(_roiSecondController.text.trim()) ?? 50.0;
    return buildApiUri(
      '/roi_marker/frame',
      queryParameters: {
        'camera_id': widget.cameraId.toString(),
        'second': second.toStringAsFixed(1),
      },
    ).toString();
  }

  Future<void> _openExternalUrl(String url) async {
    final uri = Uri.parse(url);
    final opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!opened && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('ไม่สามารถเปิดลิงก์ได้ กรุณาคัดลอกลิงก์ไปเปิดเอง')),
      );
    }
  }

  Future<void> _copyToClipboard(String value, String label) async {
    await Clipboard.setData(ClipboardData(text: value));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('คัดลอก$labelแล้ว')),
    );
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
                          : _streamError != null && _retryCount >= _maxRetries
                              ? Center(
                                  child: Padding(
                                    padding: const EdgeInsets.all(24),
                                    child: Text(
                                      _streamError!,
                                      textAlign: TextAlign.center,
                                      style: Theme.of(context).textTheme.bodyLarge?.copyWith(color: Colors.white),
                                    ),
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
                if (!_isFullScreen && !_isAdmin) SizedBox(height: 16),
                if (!_isFullScreen && !_isAdmin)
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
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Material(
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
                  ],
                ),
              ),
            ),
          ),
          if (_isAdmin)
            SafeArea(
              child: Align(
                alignment: Alignment.bottomRight,
                child: Padding(
                  padding: const EdgeInsets.all(12.0),
                  child: Material(
                    color: Colors.transparent,
                    child: InkWell(
                      borderRadius: BorderRadius.circular(28),
                      onTap: () {
                        setState(() {
                          _showManualRoiPopup = !_showManualRoiPopup;
                        });
                      },
                      child: Ink(
                        width: 56,
                        height: 56,
                        decoration: BoxDecoration(
                          gradient: const LinearGradient(
                            colors: [Color(0xFF1D4ED8), Color(0xFF4F46E5)],
                            begin: Alignment.topLeft,
                            end: Alignment.bottomRight,
                          ),
                          shape: BoxShape.circle,
                          boxShadow: const [
                            BoxShadow(
                              color: Color(0x332563EB),
                              blurRadius: 16,
                              offset: Offset(0, 8),
                            ),
                          ],
                        ),
                        child: Icon(
                          _showManualRoiPopup ? Icons.keyboard_arrow_right : Icons.keyboard_arrow_left,
                          color: Colors.white,
                          size: 30,
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          if (_isAdmin && _showManualRoiPopup)
            SafeArea(
              child: Align(
                alignment: Alignment.centerRight,
                child: Padding(
                  padding: const EdgeInsets.only(right: 12, left: 12),
                  child: SizedBox(
                    width: 320,
                    child: Card(
                      elevation: 8,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(14),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.all(14),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                const Icon(Icons.crop_free, color: Colors.indigo),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    'Manual ROI',
                                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                                          fontWeight: FontWeight.bold,
                                        ),
                                  ),
                                ),
                                IconButton(
                                  tooltip: 'ปิด',
                                  onPressed: () {
                                    setState(() {
                                      _showManualRoiPopup = false;
                                    });
                                  },
                                  icon: const Icon(Icons.close),
                                )
                              ],
                            ),
                            const SizedBox(height: 8),
                            Text(
                              'กล้อง: ${widget.name} (ID: ${widget.cameraId})',
                              style: Theme.of(context).textTheme.bodyMedium,
                            ),
                            const SizedBox(height: 10),
                            TextField(
                              controller: _roiSecondController,
                              keyboardType: const TextInputType.numberWithOptions(decimal: true),
                              decoration: const InputDecoration(
                                labelText: 'เลือกวินาทีของเฟรม',
                                hintText: 'เช่น 50.0',
                                border: OutlineInputBorder(),
                                isDense: true,
                              ),
                            ),
                            const SizedBox(height: 10),
                            Wrap(
                              spacing: 8,
                              runSpacing: 8,
                              children: [
                                ElevatedButton.icon(
                                  onPressed: () => _openExternalUrl(_roiMarkerUrl()),
                                  icon: const Icon(Icons.open_in_new),
                                  label: const Text('เปิด ROI Marker'),
                                ),
                                OutlinedButton.icon(
                                  onPressed: () => _openExternalUrl(_roiFrameUrl()),
                                  icon: const Icon(Icons.image),
                                  label: const Text('เปิดเฟรมอ้างอิง'),
                                ),
                              ],
                            ),
                            const SizedBox(height: 10),
                            Text(
                              'URL: ${_roiMarkerUrl()}',
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                            Text(
                              'Frame: ${_roiFrameUrl()}',
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                            const SizedBox(height: 10),
                            Row(
                              children: [
                                Expanded(
                                  child: OutlinedButton(
                                    onPressed: () => _copyToClipboard(_roiMarkerUrl(), 'ลิงก์ ROI Marker'),
                                    child: const Text('คัดลอกลิงก์ ROI'),
                                  ),
                                ),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: OutlinedButton(
                                    onPressed: () => _copyToClipboard(_roiFrameUrl(), 'ลิงก์เฟรม'),
                                    child: const Text('คัดลอกลิงก์เฟรม'),
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
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
