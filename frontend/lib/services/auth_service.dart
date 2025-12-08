import 'dart:convert';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

class AuthService {
  AuthService._internal();
  static final AuthService _instance = AuthService._internal();
  factory AuthService() => _instance;

  final _secureStorage = const FlutterSecureStorage();

  String get baseUrl {
    if (defaultTargetPlatform == TargetPlatform.android) {
      return 'https://resalehub.onrender.com';
    } else {
      return 'https://resalehub.onrender.com';
    }
  }

  Future<void> signup(String email, String password) async {
    final url = Uri.parse('$baseUrl/auth/signup');
    final res = await http.post(
      url,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'email': email,
        'password': password,
      }),
    );

    if (res.statusCode != 200) {
      throw Exception('Signup failed: ${res.body}');
    }
  }

  Future<void> login(String email, String password) async {
    final url = Uri.parse('$baseUrl/auth/login');
    final res = await http.post(
      url,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'email': email,
        'password': password,
      }),
    );

    if (res.statusCode != 200) {
      throw Exception('Login failed: ${res.body}');
    }

    final data = jsonDecode(res.body) as Map<String, dynamic>;
    final token = data['access_token'] as String?;
    if (token == null) {
      throw Exception('No access_token in response');
    }

    await _saveToken(token);
  }

  Future<void> _saveToken(String token) async {
    if (Platform.isMacOS) {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('access_token', token);
    } else {
      await _secureStorage.write(key: 'access_token', value: token);
    }
  }

  Future<String?> getToken() async {
    if (Platform.isMacOS) {
      final prefs = await SharedPreferences.getInstance();
      return prefs.getString('access_token');
    } else {
      return _secureStorage.read(key: 'access_token');
    }
  }

  Future<void> logout() async {
    if (Platform.isMacOS) {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove('access_token');
    } else {
      await _secureStorage.delete(key: 'access_token');
    }
  }

  /// Call /auth/me with the stored token
  Future<Map<String, dynamic>?> getCurrentUser() async {
    final token = await getToken();
    if (token == null) return null;

    final url = Uri.parse('$baseUrl/auth/me');
    final res = await http.get(
      url,
      headers: {
        'Authorization': 'Bearer $token',
      },
    );

    if (res.statusCode != 200) {
      return null;
    }

    return jsonDecode(res.body) as Map<String, dynamic>;
  }
}
