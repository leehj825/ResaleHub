import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
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

            // Show success animation
            setState(() {
              _polling = false;
            });

            // Show success message
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text('✓ Poshmark connected successfully!'),
                backgroundColor: Colors.green,
                duration: Duration(seconds: 2),
              ),
            );

            // Navigate back after a short delay
            await Future.delayed(const Duration(milliseconds: 1500));
            if (mounted) {
              Navigator.of(context).pop(true); // Return true to indicate success
            }
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
            
            // Pairing code display
            else if (_pairingCode != null) ...[
              // Pairing Code
              Card(
                elevation: 4,
                child: Padding(
                  padding: const EdgeInsets.all(32),
                  child: Column(
                    children: [
                      Text(
                        'Your Pairing Code',
                        style: theme.textTheme.titleMedium?.copyWith(
                          color: Colors.grey[600],
                        ),
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
              
              const SizedBox(height: 32),
              
              // Instructions
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(Icons.info_outline, color: theme.primaryColor),
                          const SizedBox(width: 8),
                          Text(
                            'Instructions',
                            style: theme.textTheme.titleMedium?.copyWith(
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),
                      _buildInstructionStep(
                        '1',
                        'Install the ResaleHub Chrome Extension',
                        'Open Chrome and go to chrome://extensions/, then load the extension from the chrome_extension folder.',
                      ),
                      const SizedBox(height: 12),
                      _buildInstructionStep(
                        '2',
                        'Log in to poshmark.com',
                        'Make sure you are logged into your Poshmark account in your browser.',
                      ),
                      const SizedBox(height: 12),
                      _buildInstructionStep(
                        '3',
                        'Enter the pairing code',
                        'Click the ResaleHub extension icon, enter the code above, and click "Sync".',
                      ),
                    ],
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

  Widget _buildInstructionStep(String number, String title, String description) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 28,
          height: 28,
          decoration: BoxDecoration(
            color: Theme.of(context).primaryColor,
            shape: BoxShape.circle,
          ),
          child: Center(
            child: Text(
              number,
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.bold,
                fontSize: 14,
              ),
            ),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  fontWeight: FontWeight.w600,
                  fontSize: 14,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                description,
                style: TextStyle(
                  fontSize: 12,
                  color: Colors.grey[700],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

