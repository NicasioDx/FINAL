import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import '../config/api.dart';
import '../config/session.dart';

class ParkingHistoryScreen extends StatefulWidget {
  final bool isAdmin;

  const ParkingHistoryScreen({
    super.key,
    required this.isAdmin,
  });

  @override
  State<ParkingHistoryScreen> createState() => _ParkingHistoryScreenState();
}

class _ParkingHistoryScreenState extends State<ParkingHistoryScreen> {
  List<dynamic> _history = [];
  bool _isLoading = false;
  String? _error;
  String? _currentUsername;
  String _selectedZone = '';
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
          queryParameters: {
            'username': _currentUsername!,
          },
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
          _error = (body['detail'] ?? 'Failed to load history').toString();
          _isLoading = false;
        });
      }
    } catch (e) {
      setState(() {
        _error = 'Error: ${e.toString()}';
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
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
                        hintText: 'ค้นหาโซน (เช่น Zone A)',
                        prefixIcon: const Icon(Icons.map),
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
                              widget.isAdmin ? 'ไม่มีประวัติการจอด' : 'คุณยังไม่มีประวัติการจอด',
                              style: Theme.of(context).textTheme.bodyLarge,
                            ),
                          )
                        : ListView.builder(
                            itemCount: _history.length,
                            itemBuilder: (context, index) {
                              final record = _history[index];
                              return Card(
                                margin: const EdgeInsets.symmetric(
                                  horizontal: 12,
                                  vertical: 8,
                                ),
                                child: ListTile(
                                  leading: Icon(
                                    _getEventIcon(record['event_type']),
                                    color: Colors.green,
                                  ),
                                  title: Text(record['event_type'] == 'parking_success'
                                      ? 'เข้าจอดสำเร็จ'
                                      : record['event_type']),
                                  subtitle: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        'กล้อง: ${record['camera_name'] ?? record['camera_id']}',
                                      ),
                                      Text(
                                        'โซน: ${record['zone_name'] ?? 'ทั่วไป'}',
                                        style: const TextStyle(
                                          fontSize: 12,
                                        ),
                                      ),
                                      if (widget.isAdmin)
                                        Text(
                                          'ผู้ใช้: ${record['username']}',
                                          style: const TextStyle(
                                            fontSize: 12,
                                            fontWeight: FontWeight.bold,
                                          ),
                                        ),
                                      Text(
                                        _formatDateTime(record['created_at']),
                                        style: const TextStyle(
                                          fontSize: 12,
                                          color: Colors.grey,
                                        ),
                                      ),
                                    ],
                                  ),
                                  isThreeLine: widget.isAdmin,
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
      default:
        return Icons.info;
    }
  }

  String _formatDateTime(String? dateTimeStr) {
    if (dateTimeStr == null) return '';
    try {
      final dateTime = DateTime.parse(dateTimeStr);
      return '${dateTime.day}/${dateTime.month}/${dateTime.year} ${dateTime.hour}:${dateTime.minute.toString().padLeft(2, '0')}';
    } catch (e) {
      return dateTimeStr;
    }
  }
}
