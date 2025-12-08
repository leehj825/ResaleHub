// pubspec.yaml에 추가했는지 확인
// url_launcher: ^6.3.0
// http: ^1.2.0 (버전에 따라 다를 수 있음)

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:http/http.dart' as http;

import '../services/marketplace_service.dart';
import '../services/auth_service.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _marketplaceService = MarketplaceService();
  final _auth = AuthService(); // ✅ _auth 추가

  bool _loadingStatus = true;
  bool _ebayConnected = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadStatus();
  }

  Future<void> _loadStatus() async {
    setState(() {
      _loadingStatus = true;
      _error = null;
    });
    try {
      final connected = await _marketplaceService.isEbayConnected();
      if (!mounted) return;
      setState(() {
        _ebayConnected = connected;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
      });
    } finally {
      if (!mounted) return;
      setState(() {
        _loadingStatus = false;
      });
    }
  }

  Future<void> _connectEbay() async {
    try {
      final url = await _marketplaceService.getEbayConnectUrl();
      final uri = Uri.parse(url);
      await launchUrl(uri, mode: LaunchMode.externalApplication);
      // 브라우저에서 인증 후, 앱으로 돌아와서 "Refresh status"로 확인
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to open eBay auth: $e')),
      );
    }
  }

  Future<void> _disconnectEbay() async {
    try {
      await _marketplaceService.disconnectEbay();

      if (!mounted) return;

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Disconnected from eBay')),
      );

      await _loadStatus(); // 상태 다시 불러오기
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Disconnect failed: $e')),
      );
    }
  }

  Future<void> _testEbayApi() async {
    try {
      final baseUrl = _auth.baseUrl;
      final token = await _auth.getToken();
      if (token == null) throw Exception('Not logged in');

      final url = Uri.parse('$baseUrl/marketplaces/ebay/me');
      final res = await http.get(
        url,
        headers: {
          'Authorization': 'Bearer $token',
        },
      );

      if (!mounted) return;
      showDialog(
        context: context,
        builder: (_) => AlertDialog(
          title: const Text('eBay API result'),
          content: SingleChildScrollView(
            child: Text(res.body),
          ),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Test failed: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('eBay 연결 상태', style: theme.textTheme.titleMedium),
            const SizedBox(height: 8),
            if (_loadingStatus)
              const CircularProgressIndicator()
            else if (_error != null)
              Text(
                'Error: $_error',
                style: const TextStyle(color: Colors.red),
              )
            else
              Row(
                children: [
                  Icon(
                    _ebayConnected
                        ? Icons.check_circle
                        : Icons.cancel_outlined,
                    color: _ebayConnected ? Colors.green : Colors.grey,
                  ),
                  const SizedBox(width: 8),
                  Text(
                    _ebayConnected ? 'Connected' : 'Not connected',
                    style: theme.textTheme.bodyLarge,
                  ),
                  const Spacer(),

                  // 연결 안 됐을 때: Connect만
                  if (!_ebayConnected)
                    TextButton(
                      onPressed: _connectEbay,
                      child: const Text('Connect'),
                    ),

                  // 연결 됐을 때: Disconnect + Re-connect
                  if (_ebayConnected) ...[
                    TextButton(
                      onPressed: _disconnectEbay,
                      child: const Text('Disconnect'),
                    ),
                    TextButton(
                      onPressed: _connectEbay,
                      child: const Text('Re-connect'),
                    ),
                  ],
                ],
              ),
            const SizedBox(height: 16),
            TextButton(
              onPressed: _loadStatus,
              child: const Text('Refresh status'),
            ),
            const SizedBox(height: 16),
            TextButton(
              onPressed: _testEbayApi,
              child: const Text('Test eBay API'),
            ),
          ],
        ),
      ),
    );
  }
}
