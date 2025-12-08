class MarketplaceInfo {
  final String marketplace;
  final String? listingUrl;
  final String status;
  final String? externalItemId;

  MarketplaceInfo({
    required this.marketplace,
    this.listingUrl,
    required this.status,
    this.externalItemId,
  });

  factory MarketplaceInfo.fromJson(Map<String, dynamic> json) {
    return MarketplaceInfo(
      marketplace: json['marketplace'] ?? '',
      listingUrl: json['external_url'], // 백엔드 스키마랑 이름 맞춤 (external_url)
      status: json['status'] ?? '',
      externalItemId: json['external_item_id'],
    );
  }
}

class Listing {
  final int id;
  final String title;
  final String description;
  final double price;
  final List<MarketplaceInfo> marketplaces; // 추가됨

  Listing({
    required this.id,
    required this.title,
    required this.description,
    required this.price,
    this.marketplaces = const [],
  });

  factory Listing.fromJson(Map<String, dynamic> json) {
    var mkList = json['marketplace_links'] as List? ?? []; // 백엔드 필드명 주의
    List<MarketplaceInfo> mkData = mkList.map((i) => MarketplaceInfo.fromJson(i)).toList();

    return Listing(
      id: json['id'],
      title: json['title'] ?? '',
      description: json['description'] ?? '',
      price: double.tryParse(json['price'].toString()) ?? 0.0,
      marketplaces: mkData,
    );
  }
}
