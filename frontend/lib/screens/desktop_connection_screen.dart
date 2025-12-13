import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import '../services/auth_service.dart';

class DesktopConnectionScreen extends StatefulWidget {
  const DesktopConnectionScreen({super.key});

  @override
  State<DesktopConnectionScreen> createState() => _DesktopConnectionScreenState();
}

class _DesktopConnectionScreenState extends State<DesktopConnectionScreen> {
  final _authService = AuthService();
  String? _pairingCode;
  bool _loading = true;
  bool _polling = false;
  bool _connected = false;
  String? _error;
  Timer? _pollTimer;
  int _expiresInSeconds = 600;

  @override
  void initState() {
    super.initState();
    _generatePairingCode();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    super.dispose();
  }

  Future<void> _generatePairingCode() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final baseUrl = _authService.baseUrl;
      final token = await _authService.getToken();
      if (token == null) {
        throw Exception('Not logged in');
      }

      final url = Uri.parse('$baseUrl/api/auth/pairing-code');
      final response = await http.post(
        url,
        headers: {
          'Authorization': 'Bearer $token',
          'Content-Type': 'application/json',
        },
      );

      if (response.statusCode != 200) {
        throw Exception('Failed to generate pairing code: ${response.body}');
      }

      final data = jsonDecode(response.body) as Map<String, dynamic>;
      setState(() {
        _pairingCode = data['code'] as String;
        _expiresInSeconds = data['expires_in_seconds'] as int? ?? 600;
        _loading = false;
      });

      // Start polling for status
      _startPolling();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  void _startPolling() {
    if (_pairingCode == null) return;

    setState(() {
      _polling = true;
    });

    _pollTimer = Timer.periodic(const Duration(seconds: 3), (timer) async {
      if (!mounted) {
        timer.cancel();
        return;
      }

      try {
        final baseUrl = _authService.baseUrl;
        final url = Uri.parse('$baseUrl/api/auth/pairing-status/$_pairingCode');
        final response = await http.get(url);

        if (response.statusCode == 200) {
          final data = jsonDecode(response.body) as Map<String, dynamic>;
          final status = data['status'] as String;
          final cookiesReceived = data['cookies_received'] as bool? ?? false;

          if (status == 'success' && cookiesReceived) {
            timer.cancel();
            if (!mounted) return;

            // Show success state
            setState(() {
              _polling = false;
              _connected = true;
            });
          } else if (status == 'expired' || status == 'not_found') {
            timer.cancel();
            if (!mounted) return;
            setState(() {
              _polling = false;
              _error = 'Pairing code expired. Please try again.';
            });
          }
        }
      } catch (e) {
        // Ignore polling errors, just continue
        debugPrint('Polling error: $e');
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Desktop Connection'),
        leading: IconButton(
          icon: const Icon(Icons.close),
          onPressed: () {
            _pollTimer?.cancel();
            Navigator.of(context).pop(false);
          },
        ),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const SizedBox(height: 40),
            
            // Icon
            Icon(
              Icons.desktop_windows,
              size: 80,
              color: theme.primaryColor,
            ),
            
            const SizedBox(height: 32),
            
            // Title
            Text(
              'Connect Desktop Browser',
              style: theme.textTheme.headlineSmall?.copyWith(
                fontWeight: FontWeight.bold,
              ),
              textAlign: TextAlign.center,
            ),
            
            const SizedBox(height: 16),
            
            // Loading state
            if (_loading)
              const Center(
                child: Padding(
                  padding: EdgeInsets.all(32.0),
                  child: CircularProgressIndicator(),
                ),
              )
            
            // Error state
            else if (_error != null)
              Card(
                color: Colors.red[50],
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    children: [
                      Icon(Icons.error_outline, color: Colors.red[700], size: 48),
                      const SizedBox(height: 12),
                      Text(
                        _error!,
                        style: TextStyle(color: Colors.red[700]),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 16),
                      ElevatedButton(
                        onPressed: _generatePairingCode,
                        child: const Text('Retry'),
                      ),
                    ],
                  ),
                ),
              )
            
            // Success state
            else if (_connected) ...[
              // Success message with large icon
              Card(
                elevation: 4,
                color: Colors.green[50],
                child: Padding(
                  padding: const EdgeInsets.all(48),
                  child: Column(
                    children: [
                      Icon(
                        Icons.check_circle,
                        size: 120,
                        color: Colors.green[600],
                      ),
                      const SizedBox(height: 24),
                      Text(
                        'Connection Successful!',
                        style: theme.textTheme.headlineMedium?.copyWith(
                          fontWeight: FontWeight.bold,
                          color: Colors.green[700],
                        ),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 16),
                      Text(
                        'You can now close this window',
                        style: theme.textTheme.bodyLarge?.copyWith(
                          color: Colors.grey[700],
                        ),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 32),
                      ElevatedButton.icon(
                        onPressed: () {
                          Navigator.of(context).pop(true);
                        },
                        icon: const Icon(Icons.check),
                        label: const Text('Done'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.green[600],
                          foregroundColor: Colors.white,
                          padding: const EdgeInsets.symmetric(
                            horizontal: 32,
                            vertical: 16,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ]
            
            // Pairing code display
            else if (_pairingCode != null) ...[
              // Step-by-step guide
              Card(
                elevation: 2,
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Connection Steps',
                        style: theme.textTheme.titleLarge?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 20),
                      // Step 1
                      _buildStepCard(
                        context,
                        stepNumber: 1,
                        title: 'Install Chrome Extension',
                        description: 'Click the icon to install the Chrome extension',
                        icon: Icons.extension,
                        button: ElevatedButton.icon(
                          onPressed: () {
                            // Open Chrome extension installation guide
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                content: Text('Load the extension from chrome://extensions/'),
                                duration: Duration(seconds: 3),
                              ),
                            );
                          },
                          icon: const Icon(Icons.open_in_new),
                          label: const Text('Open Installation Guide'),
                        ),
                      ),
                      const SizedBox(height: 16),
                      // Step 2
                      _buildStepCard(
                        context,
                        stepNumber: 2,
                        title: 'Verify Poshmark Login on PC',
                        description: 'Make sure you are logged into poshmark.com in your desktop browser',
                        icon: Icons.login,
                      ),
                      const SizedBox(height: 16),
                      // Step 3
                      _buildStepCard(
                        context,
                        stepNumber: 3,
                        title: 'Enter Pairing Code Below',
                        description: 'Enter the code below in the extension popup and click "Sync"',
                        icon: Icons.code,
                      ),
                    ],
                  ),
                ),
              ),
              
              const SizedBox(height: 24),
              
              // Pairing Code (tappable to copy)
              GestureDetector(
                onTap: () {
                  Clipboard.setData(ClipboardData(text: _pairingCode!));
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('Copied to clipboard'),
                      duration: Duration(seconds: 2),
                      backgroundColor: Colors.green,
                    ),
                  );
                },
                child: Card(
                  elevation: 4,
                  child: Padding(
                    padding: const EdgeInsets.all(32),
                    child: Column(
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Text(
                              'Your Pairing Code',
                              style: theme.textTheme.titleMedium?.copyWith(
                                color: Colors.grey[600],
                              ),
                            ),
                            const SizedBox(width: 8),
                            Icon(
                              Icons.copy,
                              size: 18,
                              color: Colors.grey[600],
                            ),
                          ],
                        ),
                        const SizedBox(height: 16),
                        Text(
                          _pairingCode!,
                          style: theme.textTheme.displayLarge?.copyWith(
                            fontWeight: FontWeight.bold,
                            letterSpacing: 8,
                            color: theme.primaryColor,
                          ),
                          textAlign: TextAlign.center,
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'Tap to copy',
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: Colors.grey[500],
                            fontStyle: FontStyle.italic,
                          ),
                        ),
                        const SizedBox(height: 16),
                        if (_polling)
                          Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  valueColor: AlwaysStoppedAnimation<Color>(
                                    theme.primaryColor,
                                  ),
                                ),
                              ),
                              const SizedBox(width: 8),
                              Text(
                                'Waiting for connection...',
                                style: theme.textTheme.bodyMedium?.copyWith(
                                  color: Colors.grey[600],
                                ),
                              ),
                            ],
                          ),
                      ],
                    ),
                  ),
                ),
              ),
              
              const SizedBox(height: 24),
              
              // Expiry info
              Text(
                'This code expires in ${_expiresInSeconds ~/ 60} minutes',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: Colors.grey[600],
                ),
                textAlign: TextAlign.center,
              ),
              
              const SizedBox(height: 16),
              
              // Regenerate button
              OutlinedButton.icon(
                onPressed: _generatePairingCode,
                icon: const Icon(Icons.refresh),
                label: const Text('Generate New Code'),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildStepCard(
    BuildContext context, {
    required int stepNumber,
    required String title,
    required String description,
    required IconData icon,
    Widget? button,
  }) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.grey[50],
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.grey[300]!),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: theme.primaryColor,
                  shape: BoxShape.circle,
                ),
                child: Center(
                  child: Text(
                    '$stepNumber',
                    style: const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.bold,
                      fontSize: 16,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Icon(icon, color: theme.primaryColor, size: 24),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    fontSize: 16,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Padding(
            padding: const EdgeInsets.only(left: 44),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  description,
                  style: TextStyle(
                    fontSize: 14,
                    color: Colors.grey[700],
                  ),
                ),
                if (button != null) ...[
                  const SizedBox(height: 12),
                  button,
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

}

