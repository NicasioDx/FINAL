import 'dart:convert';
import 'dart:async';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import '../config/api.dart';
import '../config/theme_controller.dart';

class AddCameraScreen extends StatefulWidget {
  @override
  _AddCameraScreenState createState() => _AddCameraScreenState();
}

class _AddCameraScreenState extends State<AddCameraScreen> {
  final _nameController = TextEditingController();
  final _ipController = TextEditingController();
  final _userController = TextEditingController();
  final _passController = TextEditingController();
  final _zoneController = TextEditingController(text: 'ทั่วไป');

  WebSocketChannel? _previewChannel;
  Uint8List? _previewImageBytes;
  bool _isStreaming = false;
  String? _streamError;
  Timer? _reconnectDebounce;

  void _toggleStream() {
    if (_isStreaming) {
      _stopPreviewStream(clearImage: true);
    } else {
      if (_ipController.text.trim().isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('กรุณากรอก IP Address ก่อนทดสอบ')),
        );
        return;
      }
      _startPreviewStream();
    }
  }

  String _buildPreviewWsUrl() {
    final baseUri = Uri.parse(BASE_URL);
    final wsScheme = baseUri.scheme == 'https' ? 'wss' : 'ws';
    return baseUri.replace(scheme: wsScheme, path: '/ws/preview_camera').toString();
  }

  void _startPreviewStream() {
    _stopPreviewStream(clearImage: false);

    final wsUrl = _buildPreviewWsUrl();
    final channel = WebSocketChannel.connect(Uri.parse(wsUrl));
    _previewChannel = channel;

    setState(() {
      _isStreaming = true;
      _streamError = null;
    });

    try {
      channel.sink.add(
        jsonEncode({
          "ip": _ipController.text,
          "username": _userController.text,
          "password": _passController.text,
        }),
      );

      channel.stream.listen(
        (data) {
          if (!mounted || !_isStreaming) return;

          if (data is Uint8List) {
            setState(() {
              _previewImageBytes = data;
              _streamError = null;
            });
            return;
          }

          if (data is List<int>) {
            setState(() {
              _previewImageBytes = Uint8List.fromList(data);
              _streamError = null;
            });
            return;
          }

          if (data is String && data.startsWith('error:')) {
            _handleStreamError(data.replaceFirst('error:', '').trim());
          }
        },
        onError: (error) {
          _handleStreamError('เชื่อมต่อ preview ไม่สำเร็จ');
        },
        onDone: () {
          if (_isStreaming) {
            _handleStreamError('การเชื่อมต่อ preview ถูกปิด');
          }
        },
      );
    } catch (_) {
      _handleStreamError('เชื่อมต่อ preview ไม่สำเร็จ');
    }
  }

  void _handleStreamError(String message) {
    if (!mounted) return;

    _previewChannel?.sink.close();
    _previewChannel = null;

    setState(() {
      _isStreaming = false;
      _streamError = message;
    });
  }

  void _stopPreviewStream({required bool clearImage}) {
    _previewChannel?.sink.close();
    _previewChannel = null;

    if (!mounted) return;
    setState(() {
      _isStreaming = false;
      _streamError = null;
      if (clearImage) {
        _previewImageBytes = null;
      }
    });
  }

  void _onInputChanged(String _) {
    if (!_isStreaming) return;

    _reconnectDebounce?.cancel();
    _reconnectDebounce = Timer(const Duration(milliseconds: 700), () {
      if (mounted && _isStreaming) {
        _startPreviewStream();
      }
    });
  }

  // ฟังก์ชันบันทึกข้อมูลกล้องลงฐานข้อมูล
  Future<void> _saveCamera() async {
    // ตรวจสอบก่อนว่ากรอกข้อมูลครบไหม
    if (_nameController.text.isEmpty || _ipController.text.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('กรุณากรอกชื่อกล้องและ IP Address')),
      );
      return;
    }

    try {
      final response = await http.post(
        Uri.parse('$BASE_URL/add_camera'),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode({
          "camera_name": _nameController.text,
          "ip": _ipController.text,
          "username": _userController.text,
          "password": _passController.text,
          "zone_name": _zoneController.text.trim().isEmpty ? 'ทั่วไป' : _zoneController.text.trim(),
        }),
      );

      final result = jsonDecode(response.body);

      if (response.statusCode == 200 && result['status'] == 'success') {
        // บันทึกสำเร็จ
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('บันทึกข้อมูลกล้องสำเร็จ!')),
        );
        
        // หยุดการ Stream และกลับไปหน้าหลัก
        _stopPreviewStream(clearImage: true);
        Navigator.pop(context); 
      } else {
        throw Exception(result['message'] ?? 'เกิดข้อผิดพลาดในการบันทึก');
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('ไม่สามารถบันทึกได้: $e')),
      );
    }
  }

  @override
  void dispose() {
    _reconnectDebounce?.cancel();
    _previewChannel?.sink.close();
    _nameController.dispose();
    _ipController.dispose();
    _userController.dispose();
    _passController.dispose();
    _zoneController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text("เพิ่มกล้องใหม่"),
        centerTitle: true,
        actions: const [ThemeModeToggleButton()],
      ),
      body: Padding(
        padding: EdgeInsets.all(24),
        child: Row(
          children: [
            Expanded(
              flex: 2,
              child: Card(
                elevation: 4,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Padding(
                  padding: EdgeInsets.all(30),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'ข้อมูลกล้อง',
                        style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      SizedBox(height: 24),
                      _buildTextField(_nameController, "ชื่อกล้อง", Icons.camera_alt),
                      _buildTextField(
                        _ipController,
                        "IP Address",
                        Icons.network_check,
                        triggerPreviewReconnect: true,
                      ),
                      _buildTextField(
                        _userController,
                        "Username",
                        Icons.person,
                        triggerPreviewReconnect: true,
                      ),
                      _buildTextField(
                        _passController,
                        "Password",
                        Icons.lock,
                        isPassword: true,
                        triggerPreviewReconnect: true,
                      ),
                      _buildTextField(_zoneController, "โซน (เช่น Zone A)", Icons.map),
                      SizedBox(height: 30),
                      Center(
                        child: ElevatedButton.icon(
                          onPressed: _toggleStream,
                          icon: Icon(_isStreaming ? Icons.stop : Icons.videocam),
                          label: Text(_isStreaming ? "หยุดทดสอบ" : "ทดสอบการเชื่อมต่อ"),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            SizedBox(width: 24),
            Expanded(
              flex: 3,
              child: Card(
                elevation: 4,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Padding(
                  padding: EdgeInsets.all(30),
                  child: Column(
                    children: [
                      Text(
                        "ภาพตัวอย่างกล้อง",
                        style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      SizedBox(height: 20),
                      Container(
                        width: double.infinity,
                        height: 400,
                        decoration: BoxDecoration(
                          color: Colors.black,
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: _previewImageBytes != null
                            ? ClipRRect(
                                borderRadius: BorderRadius.circular(10),
                                child: Image.memory(
                                  _previewImageBytes!,
                                  fit: BoxFit.cover,
                                  gaplessPlayback: true,
                                ),
                              )
                            : Center(
                                child: Column(
                                  mainAxisAlignment: MainAxisAlignment.center,
                                  children: [
                                    Icon(
                                      Icons.videocam_off,
                                      size: 64,
                                      color: Colors.white54,
                                    ),
                                    SizedBox(height: 16),
                                    Text(
                                      _streamError ?? "ไม่มีสัญญาณภาพ",
                                      style: TextStyle(color: Colors.white),
                                      textAlign: TextAlign.center,
                                    ),
                                  ],
                                ),
                              ),
                      ),
                      SizedBox(height: 40),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          _buildActionButton("บันทึก", Colors.green, Icons.check, () {
                            _saveCamera();
                          }),
                          SizedBox(width: 20),
                          _buildActionButton("ยกเลิก", Colors.red, Icons.close, () {
                            Navigator.pop(context);
                          }),
                        ],
                      )
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildTextField(
    TextEditingController controller,
    String hint,
    IconData icon, {
    bool isPassword = false,
    bool triggerPreviewReconnect = false,
  }) {
    return Container(
      margin: EdgeInsets.only(bottom: 15),
      child: TextField(
        controller: controller,
        onChanged: triggerPreviewReconnect ? _onInputChanged : null,
        obscureText: isPassword,
        decoration: InputDecoration(
          hintText: hint,
          prefixIcon: Icon(icon),
          filled: true,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(8),
          ),
        ),
      ),
    );
  }

  Widget _buildActionButton(String label, Color color, IconData icon, VoidCallback onPressed) {
    return ElevatedButton.icon(
      onPressed: onPressed,
      icon: Icon(icon),
      label: Text(label),
      style: ElevatedButton.styleFrom(
        backgroundColor: color,
        foregroundColor: Colors.white,
        padding: EdgeInsets.symmetric(horizontal: 40, vertical: 15),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(8),
        ),
      ),
    );
  }
}