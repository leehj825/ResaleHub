// lib/models/listing.dart

class MarketplaceInfo {
  final String marketplace;
  final String? listingUrl;
  final String status;
  final String? externalItemId;
  
  // 상세 정보를 위한 필드
  final String? sku;
  final String? offerId;

  MarketplaceInfo({
    required this.marketplace,
    this.listingUrl,
    required this.status,
    this.externalItemId,
    this.sku,
    this.offerId,
  });

  factory MarketplaceInfo.fromJson(Map<String, dynamic> json) {
    return MarketplaceInfo(
      marketplace: json['marketplace'] ?? '',
      listingUrl: json['external_url'],
      status: json['status'] ?? '',
      externalItemId: json['external_item_id'],
      sku: json['sku'],
      offerId: json['offer_id'],
    );
  }
}

class Listing {
  final int id;
  final String title;
  final String? description;
  final double price;

  // [필수 필드]
  final String currency;
  final String status;
  final String? thumbnailUrl;

  // [추가됨] Import 된 아이템의 SKU와 Condition을 최상위에서 접근하기 위함
  final String? sku;
  final String? condition;

  // [상세 화면용]
  final List<String> imageUrls;
  
  // [마켓플레이스 연동 정보]
  final List<MarketplaceInfo> marketplaces;

  Listing({
    required this.id,
    required this.title,
    this.description,
    required this.price,
    this.currency = 'USD',
    this.status = 'draft',
    this.thumbnailUrl,
    this.sku,        // [추가]
    this.condition,  // [추가]
    this.imageUrls = const [],
    this.marketplaces = const [],
  });

  factory Listing.fromJson(Map<String, dynamic> json) {
    // 마켓플레이스 정보 파싱
    var mkList = json['marketplace_links'] as List? ?? [];
    List<MarketplaceInfo> marketplacesData = 
        mkList.map((i) => MarketplaceInfo.fromJson(i)).toList();

    return Listing(
      id: json['id'] as int,
      title: json['title'] as String,
      description: json['description'] as String?,
      
      price: double.tryParse(json['price'].toString()) ?? 0.0,
      
      currency: json['currency'] as String? ?? 'USD',
      status: json['status'] as String? ?? 'draft',
      thumbnailUrl: json['thumbnail_url'] as String?,
      
      // [추가됨] 백엔드 JSON 매핑
      sku: json['sku'] as String?,
      condition: json['condition'] as String?,
      
      imageUrls: json['image_urls'] != null 
          ? List<String>.from(json['image_urls']) 
          : [],
      
      marketplaces: marketplacesData,
    );
  }

  // 썸네일 전체 URL 헬퍼 메서드
  String? fullThumbnailUrl(String baseUrl) {
    if (thumbnailUrl == null) return null;
    return '$baseUrl$thumbnailUrl';
  }
}