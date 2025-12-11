// lib/screens/settings_screen.dart

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:http/http.dart' as http;

import '../services/marketplace_service.dart';
import '../services/auth_service.dart';
import 'ebay_inventory_screen.dart'; // [추가] 인벤토리 화면 임포트
import 'poshmark_inventory_screen.dart'; // [추가] Poshmark 인벤토리 화면 임포트

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _marketplaceService = MarketplaceService();
  final _auth = AuthService();

  bool _loadingStatus = true;
  bool _ebayConnected = false;
  bool _poshmarkConnected = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadStatus();
  }

  /// [수정됨] eBay 인벤토리 화면으로 이동
  void _openEbayInventory() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => const EbayInventoryScreen(),
      ),
    );
  }

  /// Poshmark 인벤토리 화면으로 이동
  void _openPoshmarkInventory() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => const PoshmarkInventoryScreen(),
      ),
    );
  }

  Future<void> _loadStatus() async {
    setState(() {
      _loadingStatus = true;
      _error = null;
    });
    try {
      final ebayConnected = await _marketplaceService.isEbayConnected();
      final poshmarkConnected = await _marketplaceService.isPoshmarkConnected();
      if (!mounted) return;
      setState(() {
        _ebayConnected = ebayConnected;
        _poshmarkConnected = poshmarkConnected;
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
      
      if (await canLaunchUrl(uri)) {
        await launchUrl(uri, mode: LaunchMode.externalApplication);
        // 브라우저에서 인증 후, 앱으로 돌아와서 "Refresh status"로 확인
      } else {
        throw Exception('Could not launch $url');
      }
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

  Future<void> _connectPoshmark() async {
    try {
      final url = await _marketplaceService.getPoshmarkConnectUrl();
      final uri = Uri.parse(url);
      
      if (await canLaunchUrl(uri)) {
        await launchUrl(uri, mode: LaunchMode.externalApplication);
        // 브라우저에서 인증 후, 앱으로 돌아와서 "Refresh status"로 확인
      } else {
        throw Exception('Could not launch $url');
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to open Poshmark connect: $e')),
      );
    }
  }

  Future<void> _disconnectPoshmark() async {
    try {
      await _marketplaceService.disconnectPoshmark();

      if (!mounted) return;

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Disconnected from Poshmark')),
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
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Close'),
            ),
          ],
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
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('eBay Connection', style: theme.textTheme.titleMedium),
            const SizedBox(height: 8),
            if (_loadingStatus)
              const Center(child: CircularProgressIndicator())
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
                ],
              ),
            
            const SizedBox(height: 16),
            
            // 연결 상태에 따른 버튼들
            Row(
              children: [
                if (!_ebayConnected)
                  ElevatedButton(
                    onPressed: _connectEbay,
                    child: const Text('Connect eBay'),
                  ),
                if (_ebayConnected) ...[
                  OutlinedButton(
                    onPressed: _disconnectEbay,
                    child: const Text('Disconnect'),
                  ),
                  const SizedBox(width: 8),
                  OutlinedButton(
                    onPressed: _connectEbay,
                    child: const Text('Re-connect'),
                  ),
                ],
              ],
            ),

            const Divider(height: 32),

            // Poshmark Connection Section
            Text('Poshmark Connection', style: theme.textTheme.titleMedium),
            const SizedBox(height: 8),
            if (_loadingStatus)
              const Center(child: CircularProgressIndicator())
            else if (_error != null)
              Text(
                'Error: $_error',
                style: const TextStyle(color: Colors.red),
              )
            else
              Row(
                children: [
                  Icon(
                    _poshmarkConnected
                        ? Icons.check_circle
                        : Icons.cancel_outlined,
                    color: _poshmarkConnected ? Colors.green : Colors.grey,
                  ),
                  const SizedBox(width: 8),
                  Text(
                    _poshmarkConnected ? 'Connected' : 'Not connected',
                    style: theme.textTheme.bodyLarge,
                  ),
                ],
              ),
            
            const SizedBox(height: 16),
            
            // Poshmark 연결 상태에 따른 버튼들
            Row(
              children: [
                if (!_poshmarkConnected)
                  ElevatedButton(
                    onPressed: _connectPoshmark,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFFE31837), // Poshmark brand color
                      foregroundColor: Colors.white,
                    ),
                    child: const Text('Connect Poshmark'),
                  ),
                if (_poshmarkConnected) ...[
                  OutlinedButton(
                    onPressed: _disconnectPoshmark,
                    child: const Text('Disconnect'),
                  ),
                  const SizedBox(width: 8),
                  OutlinedButton(
                    onPressed: _connectPoshmark,
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: Color(0xFFE31837)),
                    ),
                    child: const Text('Re-connect'),
                  ),
                ],
              ],
            ),

            const Divider(height: 32),

            Text('Tools', style: theme.textTheme.titleMedium),
            const SizedBox(height: 8),
            
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                ActionChip(
                  avatar: const Icon(Icons.refresh),
                  label: const Text('Refresh Status'),
                  onPressed: _loadStatus,
                ),
                ActionChip(
                  avatar: const Icon(Icons.api),
                  label: const Text('Test API (Log)'),
                  onPressed: _testEbayApi,
                ),
                // [수정됨] 인벤토리 화면으로 이동하는 버튼
                ActionChip(
                  avatar: const Icon(Icons.inventory_2_outlined),
                  label: const Text('eBay Sandbox Inventory'),
                  onPressed: _openEbayInventory,
                ),
                ActionChip(
                  avatar: const Icon(Icons.inventory_2_outlined),
                  label: const Text('Poshmark Inventory'),
                  onPressed: _openPoshmarkInventory,
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}