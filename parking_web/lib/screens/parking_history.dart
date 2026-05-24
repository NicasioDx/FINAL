import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import '../config/api.dart';
import '../config/session.dart';

class ParkingHistoryScreen extends StatefulWidget {
  final bool isAdmin;

  const ParkingHistoryScreen({super.key, required this.isAdmin});

  @override
  State<ParkingHistoryScreen> createState() => _ParkingHistoryScreenState();
}

class _ParkingHistoryScreenState extends State<ParkingHistoryScreen> {
  List<dynamic> _history = [];
  bool _isLoading = false;
  String? _error;
  String? _currentUsername;
  final TextEditingController _zoneFilterController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _loadHistory();
  }

  @override
  void dispose() {
    _zoneFilterController.dispose();
    super.dispose();
  }

  Future<void> _loadHistory({String? zoneFilter}) async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      Uri uri;
      if (widget.isAdmin) {
        uri = buildApiUri(
          '/parking_history/admin',
          queryParameters: {
            if (zoneFilter != null && zoneFilter.trim().isNotEmpty)
              'zone_name': zoneFilter.trim(),
          },
        );
      } else {
        _currentUsername ??= await SessionStore.getUsername();
        if ((_currentUsername ?? '').isEmpty) {
          throw Exception('ไม่พบข้อมูลผู้ใช้ในระบบ');
        }
        uri = buildApiUri(
          '/parking_history',
          queryParameters: {'username': _currentUsername!},
        );
      }

      final response = await http.get(uri, headers: buildApiHeaders());

      if (response.statusCode == 200) {
        final body = jsonDecode(response.body);
        setState(() {
          _history = body['data'] ?? [];
          _isLoading = false;
        });
      } else {
        final body = jsonDecode(response.body);
        setState(() {
          _error = _cleanText(body['detail'] ?? 'โหลดประวัติไม่สำเร็จ');
          _isLoading = false;
        });
      }
    } catch (e) {
      setState(() {
        _error = 'เกิดข้อผิดพลาด: ${_cleanText(e.toString())}';
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF7F8FA),
      appBar: AppBar(
        title: Text(widget.isAdmin ? 'ประวัติการจอด (แอดมิน)' : 'ประวัติการจอดของฉัน'),
        centerTitle: true,
      ),
      body: Column(
        children: [
          if (widget.isAdmin)
            Padding(
              padding: const EdgeInsets.all(16.0),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _zoneFilterController,
                      decoration: InputDecoration(
                        hintText: 'ค้นหาโซน เช่น Zone A',
                        prefixIcon: const Icon(Icons.map),
                        filled: true,
                        fillColor: Colors.white,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(8),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  ElevatedButton.icon(
                    onPressed: () {
                      _loadHistory(zoneFilter: _zoneFilterController.text);
                    },
                    icon: const Icon(Icons.search),
                    label: const Text('ค้นหา'),
                  ),
                ],
              ),
            ),
          Expanded(
            child: _isLoading
                ? const Center(child: CircularProgressIndicator())
                : _error != null
                ? Center(child: Text(_error!))
                : _history.isEmpty
                ? Center(
                    child: Text(
                      widget.isAdmin
                          ? 'ไม่มีประวัติการจอด'
                          : 'คุณยังไม่มีประวัติการจอด',
                      style: Theme.of(context).textTheme.bodyLarge,
                    ),
                  )
                : ListView.builder(
                    padding: const EdgeInsets.only(bottom: 16),
                    itemCount: _history.length,
                    itemBuilder: (context, index) {
                      final record = _history[index];
                      final eventType = (record['event_type'] ?? '').toString();
                      final eventColor = _getEventColor(eventType);
                      final cameraName = _cleanText(
                        record['camera_name'] ?? record['camera_id'] ?? '-',
                      );
                      final zoneName = _cleanText(
                        record['zone_name'] ?? 'ทั่วไป',
                      );
                      final username = _cleanText(
                        record['username'] ?? 'ไม่ระบุ',
                      );

                      return Card(
                        elevation: 1,
                        margin: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 8,
                        ),
                        color: Colors.white,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8),
                          side: BorderSide(
                            color: eventColor.withValues(alpha: 0.45),
                            width: 1.2,
                          ),
                        ),
                        child: Container(
                          decoration: BoxDecoration(
                            border: Border(
                              left: BorderSide(color: eventColor, width: 6),
                            ),
                          ),
                          child: ListTile(
                            contentPadding: const EdgeInsets.symmetric(
                              horizontal: 16,
                              vertical: 12,
                            ),
                            leading: CircleAvatar(
                              radius: 20,
                              backgroundColor: eventColor,
                              child: Icon(
                                _getEventIcon(eventType),
                                color: Colors.white,
                                size: 22,
                              ),
                            ),
                            title: Row(
                              children: [
                                Expanded(
                                  child: Text(
                                    _getEventTitle(eventType),
                                    style: TextStyle(
                                      color: eventColor,
                                      fontSize: 16,
                                      fontWeight: FontWeight.w800,
                                    ),
                                  ),
                                ),
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 10,
                                    vertical: 5,
                                  ),
                                  decoration: BoxDecoration(
                                    color: eventColor.withValues(alpha: 0.12),
                                    borderRadius: BorderRadius.circular(6),
                                  ),
                                  child: Text(
                                    _getEventBadge(eventType),
                                    style: TextStyle(
                                      color: eventColor,
                                      fontSize: 12,
                                      fontWeight: FontWeight.w800,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                            subtitle: Padding(
                              padding: const EdgeInsets.only(top: 8),
                              child: DefaultTextStyle(
                                style: const TextStyle(
                                  color: Color(0xFF344054),
                                  fontSize: 14,
                                  height: 1.35,
                                ),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text('กล้อง: $cameraName'),
                                    Text('โซน: $zoneName'),
                                    if (record['slot_number'] != null)
                                      Text(
                                        'ช่องจอด: ${record['slot_number']}',
                                        style: const TextStyle(
                                          color: Color(0xFF101828),
                                          fontWeight: FontWeight.w800,
                                        ),
                                      ),
                                    if (widget.isAdmin)
                                      Text(
                                        'ผู้ใช้: $username',
                                        style: const TextStyle(
                                          color: Color(0xFF101828),
                                          fontWeight: FontWeight.w700,
                                        ),
                                      ),
                                    const SizedBox(height: 2),
                                    Text(
                                      _formatDateTime(record['created_at']),
                                      style: const TextStyle(
                                        fontSize: 13,
                                        color: Color(0xFF667085),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                            isThreeLine: true,
                          ),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }

  IconData _getEventIcon(String eventType) {
    switch (eventType) {
      case 'parking_success':
        return Icons.check_circle;
      case 'parking_auto':
        return Icons.local_parking;
      case 'parking_exit':
        return Icons.logout;
      default:
        return Icons.info;
    }
  }

  Color _getEventColor(String eventType) {
    switch (eventType) {
      case 'parking_success':
        return const Color(0xFF2E7D32);
      case 'parking_auto':
        return const Color(0xFF1976D2);
      case 'parking_exit':
        return const Color(0xFFEF6C00);
      default:
        return const Color(0xFF667085);
    }
  }

  String _getEventBadge(String eventType) {
    switch (eventType) {
      case 'parking_success':
        return 'เข้า';
      case 'parking_auto':
        return 'AUTO';
      case 'parking_exit':
        return 'ออก';
      default:
        return eventType;
    }
  }

  String _getEventTitle(String eventType) {
    switch (eventType) {
      case 'parking_success':
        return 'เข้าจอดสำเร็จ';
      case 'parking_auto':
        return 'ตรวจพบรถจอดอัตโนมัติ';
      case 'parking_exit':
        return 'รถออกจากช่องจอดแล้ว';
      default:
        return eventType;
    }
  }

  String _cleanText(dynamic value) {
    var text = (value ?? '').toString();
    for (var i = 0; i < 2; i++) {
      if (!_looksMojibake(text)) break;
      try {
        text = utf8.decode(latin1.encode(text));
      } catch (_) {
        break;
      }
    }
    return text;
  }

  bool _looksMojibake(String text) {
    return text.contains('à') ||
        text.contains('Ã') ||
        text.contains('Â') ||
        text.contains('â');
  }

  String _formatDateTime(String? dateTimeStr) {
    if (dateTimeStr == null) return '';
    try {
      final dateTime = DateTime.parse(dateTimeStr);
      return '${dateTime.day}/${dateTime.month}/${dateTime.year} ${dateTime.hour}:${dateTime.minute.toString().padLeft(2, '0')}';
    } catch (e) {
      return _cleanText(dateTimeStr);
    }
  }
}
