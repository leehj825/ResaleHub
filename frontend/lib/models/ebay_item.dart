class EbayItem {
  final String sku;
  final String title;
  final int quantity;
  final String? imageUrl;
  final String? condition;

  EbayItem({
    required this.sku,
    required this.title,
    required this.quantity,
    this.imageUrl,
    this.condition,
  });

  factory EbayItem.fromJson(Map<String, dynamic> json) {
    // 1. Product 정보 추출
    final product = json['product'] ?? {};
    final String title = product['title'] ?? 'No Title';
    
    // 이미지: 리스트의 첫 번째 것 가져오기
    String? img;
    if (product['imageUrls'] != null && (product['imageUrls'] as List).isNotEmpty) {
      img = product['imageUrls'][0];
    }

    // 2. 수량 정보 추출
    final availability = json['availability'] ?? {};
    final shipTo = availability['shipToLocationAvailability'] ?? {};
    final int qty = shipTo['quantity'] ?? 0;

    return EbayItem(
      sku: json['sku'] ?? '',
      title: title,
      quantity: qty,
      imageUrl: img,
      condition: json['condition'],
    );
  }
}