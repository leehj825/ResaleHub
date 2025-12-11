class PoshmarkItem {
  final String sku;
  final String listingId;
  final String title;
  final double price;
  final String? imageUrl;
  final String url;

  PoshmarkItem({
    required this.sku,
    required this.listingId,
    required this.title,
    required this.price,
    this.imageUrl,
    required this.url,
  });

  factory PoshmarkItem.fromJson(Map<String, dynamic> json) {
    return PoshmarkItem(
      sku: json['sku']?.toString() ?? '',
      listingId: json['listingId']?.toString() ?? '',
      title: json['title']?.toString() ?? 'No Title',
      price: (json['price'] is num) ? (json['price'] as num).toDouble() : 0.0,
      imageUrl: json['imageUrl']?.toString(),
      url: json['url']?.toString() ?? '',
    );
  }
}
