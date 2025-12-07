import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/listing.dart';
import 'auth_service.dart';

class ListingService {
  ListingService._internal();
  static final ListingService _instance = ListingService._internal();
  factory ListingService() => _instance;

  final _authService = AuthService();

  Future<List<Listing>> getMyListings() async {
    final baseUrl = _authService.baseUrl;
    final token = await _authService.getToken();
    if (token == null) {
      throw Exception('Not logged in');
    }

    final url = Uri.parse('$baseUrl/listings/');
    final res = await http.get(
      url,
      headers: {
        'Authorization': 'Bearer $token',
      },
    );

    if (res.statusCode != 200) {
      throw Exception('Failed to load listings: ${res.body}');
    }

    final data = jsonDecode(res.body) as List<dynamic>;
    return data
        .map((e) => Listing.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Listing> createListing({
    required String title,
    String? description,
    required double price,
    String currency = 'USD',
  }) async {
    final baseUrl = _authService.baseUrl;
    final token = await _authService.getToken();
    if (token == null) {
      throw Exception('Not logged in');
    }

    final url = Uri.parse('$baseUrl/listings/');
    final res = await http.post(
      url,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $token',
      },
      body: jsonEncode({
        'title': title,
        'description': description,
        'price': price,
        'currency': currency,
      }),
    );

    if (res.statusCode != 201) {
      throw Exception('Failed to create listing: ${res.body}');
    }

    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return Listing.fromJson(data);
  }
}
