import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../models/listing.dart';
import 'auth_service.dart';

class ListingService {
  // 기본 baseUrl (백엔드 주소)
  final String baseUrl = 'http://127.0.0.1:8000';

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

  /// 🔧 기존 listing 수정 (title/description/price/status 등 일부만 수정 가능)
  Future<Listing> updateListing(
    int listingId, {
    String? title,
    String? description,
    double? price,
    String? currency,
    String? status,
  }) async {
    final baseUrl = _authService.baseUrl;
    final token = await _authService.getToken();
    if (token == null) {
      throw Exception('Not logged in');
    }

    final url = Uri.parse('$baseUrl/listings/$listingId');

    final Map<String, dynamic> body = {};
    if (title != null) body['title'] = title;
    if (description != null) body['description'] = description;
    if (price != null) body['price'] = price;
    if (currency != null) body['currency'] = currency;
    if (status != null) body['status'] = status;

    final res = await http.put(
      url,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $token',
      },
      body: jsonEncode(body),
    );

    if (res.statusCode != 200) {
      throw Exception('Failed to update listing: ${res.body}');
    }

    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return Listing.fromJson(data);
  }

  /// 🗑 listing 삭제
  Future<void> deleteListing(int listingId) async {
    final baseUrl = _authService.baseUrl;
    final token = await _authService.getToken();
    if (token == null) {
      throw Exception('Not logged in');
    }

    final url = Uri.parse('$baseUrl/listings/$listingId');

    final res = await http.delete(
      url,
      headers: {
        'Authorization': 'Bearer $token',
      },
    );

    if (res.statusCode != 204) {
      throw Exception('Failed to delete listing: ${res.body}');
    }
  }

  /// 📷 이미지 업로드 (기존 + 새로운 사진 추가)
  Future<void> uploadImages(int listingId, List<File> files) async {
    final token = await _authService.getToken();
    if (token == null) {
      throw Exception('Not authenticated');
    }

    final baseUrl = _authService.baseUrl;
    final uri = Uri.parse('$baseUrl/listings/$listingId/images');

    final request = http.MultipartRequest('POST', uri);
    request.headers['Authorization'] = 'Bearer $token';

    for (final file in files) {
      final fileName = file.path.split('/').last;
      request.files.add(
        await http.MultipartFile.fromPath(
          'files', // FastAPI: files: List[UploadFile] = File(...)
          file.path,
          filename: fileName,
        ),
      );
    }

    final streamed = await request.send();
    final response = await http.Response.fromStream(streamed);

    if (response.statusCode != 201) {
      throw Exception('Failed to upload images: ${response.body}');
    }
  }
}
