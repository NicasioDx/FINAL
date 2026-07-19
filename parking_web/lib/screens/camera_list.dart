import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'live_view.dart';
import 'parking_history.dart';
import '../config/api.dart';
import '../config/session.dart';
import '../config/theme_controller.dart';

class CameraListScreen extends StatefulWidget {
  const CameraListScreen({super.key});
  @override
  State<CameraListScreen> createState() => _CameraListScreenState();
}

class _CameraListScreenState extends State<CameraListScreen> {
  bool _isAdmin = false;

  Future<void> _deleteCamera(Map<String, dynamic> cam) async {
    final username = await SessionStore.getUsername();
    if ((username ?? '').isEmpty) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('ไม่พบข้อมูลผู้ใช้ที่ล็อกอิน')),
        );
        return;
    }

    if (!mounted) return;
    final passwordController = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: const Text('ยืนยันลบกล้อง'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('กล้อง: ${cam['camera_name']}'),
              const SizedBox(height: 8),
              const Text('กรอกรหัสผ่านแอดมินเพื่อยืนยันการลบ'),
              const SizedBox(height: 12),
              TextField(
                controller: passwordController,
                obscureText: true,
                decoration: const InputDecoration(
                  labelText: 'รหัสผ่านแอดมิน',
                  border: OutlineInputBorder(),
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('ยกเลิก'),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
              onPressed: () {
                if (passwordController.text.trim().isEmpty) {
                  return;
                }
                Navigator.pop(context, true);
              },
              child: const Text('ลบกล้อง'),
            ),
          ],
        );
      },
    );

    if (confirmed != true) {
      passwordController.dispose();
      return;
    }

    try {
      final response = await http.post(
        buildApiUri('/delete_camera'),
        headers: buildApiHeaders(jsonBody: true),
        body: jsonEncode({
          'camera_id': cam['id'],
          'username': username,
          'password': passwordController.text,
        }),
      );

      if (!mounted) return;
      if (response.statusCode == 200) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('ลบกล้อง ${cam['camera_name']} สำเร็จ')),
        );
        setState(() {});
      } else {
        String message = 'ลบกล้องไม่สำเร็จ';
        try {
          final body = jsonDecode(response.body);
          message = body['detail']?.toString() ?? message;
        } catch (_) {}
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(message)),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('เกิดข้อผิดพลาด: $e')),
      );
    } finally {
      passwordController.dispose();
    }
  }

  @override
  void initState() {
    super.initState();
    _loadRole();
  }

  Future<void> _loadRole() async {
    final role = await SessionStore.getRole();
    setState(() {
      _isAdmin = role == 'admin';
    });
  }

  Future<List> _fetchCameras() async {
    try {
      final response = await http.get(
        buildApiUri('/get_cameras'),
        headers: buildApiHeaders(),
      );

      if (response.statusCode != 200) {
        final body = response.body.isNotEmpty ? response.body : 'ไม่มีเนื้อหา';
        throw Exception('Backend returned ${response.statusCode}: $body');
      }

      final decoded = jsonDecode(response.body);
      if (decoded is List) return decoded;
      if (decoded is Map<String, dynamic>) {
        if (decoded['data'] is List) return decoded['data'] as List;
        if (decoded['cameras'] is List) return decoded['cameras'] as List;
        throw Exception(
          'Unexpected response format: ${decoded.runtimeType} with keys ${decoded.keys.toList()}',
        );
      }

      throw Exception('Unexpected response type: ${decoded.runtimeType}');
    } catch (e) {
      throw Exception('ไม่สามารถโหลดรายการกล้อง: $e');
    }
  }

  Future<void> _logout() async {
    await SessionStore.clear();
    if (!mounted) return;
    Navigator.pushReplacementNamed(context, '/login');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(
          _isAdmin ? "รายการกล้องทั้งหมด (แอดมิน)" : "รายการกล้องของลูกค้า",
        ),
        centerTitle: true,
        actions: [
          IconButton(
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (context) => ParkingHistoryScreen(isAdmin: _isAdmin),
                ),
              );
            },
            icon: const Icon(Icons.history),
            tooltip: 'ประวัติการจอด',
          ),
          const ThemeModeToggleButton(),
          Padding(
            padding: const EdgeInsets.only(right: 8.0),
            child: ElevatedButton.icon(
              onPressed: _logout,
              icon: const Icon(Icons.logout),
              label: const Text('ออกจากระบบ'),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.red,
                foregroundColor: Colors.white,
              ),
            ),
          ),
        ],
      ),
      body: FutureBuilder<List>(
        future: _fetchCameras(),
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24.0),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(
                      Icons.error_outline,
                      size: 64,
                      color: Colors.redAccent,
                    ),
                    const SizedBox(height: 16),
                    Text(
                      'เกิดข้อผิดพลาดขณะโหลดกล้อง',
                      style: Theme.of(context).textTheme.headlineSmall,
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 12),
                    Text(
                      snapshot.error.toString(),
                      textAlign: TextAlign.center,
                      style: Theme.of(
                        context,
                      ).textTheme.bodyMedium?.copyWith(color: Colors.grey[700]),
                    ),
                    const SizedBox(height: 24),
                    ElevatedButton(
                      onPressed: () => setState(() {}),
                      child: const Text('ลองใหม่'),
                    ),
                  ],
                ),
              ),
            );
          }

          if (snapshot.connectionState == ConnectionState.waiting ||
              !snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }

          final cameras = snapshot.data!;
          if (cameras.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.videocam_off, size: 64, color: Colors.grey),
                  SizedBox(height: 16),
                  Text(
                    'ยังไม่มีกล้องที่เพิ่ม',
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                  SizedBox(height: 8),
                  if (_isAdmin)
                    Text(
                      'กดปุ่ม + เพื่อเพิ่มกล้องใหม่',
                      style: Theme.of(
                        context,
                      ).textTheme.bodyMedium?.copyWith(color: Colors.grey),
                    ),
                ],
              ),
            );
          }
          return ListView.builder(
            padding: EdgeInsets.all(16),
            itemCount: cameras.length,
            itemBuilder: (context, index) {
              final cam = cameras[index];
              return Card(
                elevation: 2,
                margin: EdgeInsets.only(bottom: 12),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                child: ListTile(
                  contentPadding: EdgeInsets.all(16),
                  leading: CircleAvatar(
                    backgroundColor: Theme.of(context).primaryColor,
                    child: Icon(Icons.videocam, color: Colors.white),
                  ),
                  title: Text(
                    cam['camera_name'],
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                  subtitle: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text("IP: ${cam['ip_address']}"),
                      Text("โซน: ${cam['zone_name'] ?? 'ทั่วไป'}"),
                    ],
                  ),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (_isAdmin)
                        IconButton(
                          tooltip: 'ลบกล้อง',
                          icon: const Icon(Icons.delete_outline, color: Colors.redAccent),
                          onPressed: () => _deleteCamera(Map<String, dynamic>.from(cam)),
                        ),
                      const Icon(Icons.arrow_forward_ios),
                    ],
                  ),
                  onTap: () {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (context) => LiveViewScreen(
                          cameraId: cam['id'],
                          ip: cam['ip_address'],
                          name: cam['camera_name'],
                        ),
                      ),
                    );
                  },
                ),
              );
            },
          );
        },
      ),
      floatingActionButton: _isAdmin
          ? FloatingActionButton(
              onPressed: () async {
                await Navigator.pushNamed(context, '/add');
                if (!mounted) return;
                // Rebuild once after returning from add camera page to fetch latest list.
                setState(() {});
              },
              tooltip: 'เพิ่มกล้องใหม่',
              child: const Icon(Icons.add),
            )
          : null,
    );
  }
}
