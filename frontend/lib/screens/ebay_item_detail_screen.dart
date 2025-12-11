import 'package:flutter/material.dart';
import 'package:frontend/models/ebay_item.dart';

class EbayItemDetailScreen extends StatelessWidget {
  final EbayItem item;

  const EbayItemDetailScreen({super.key, required this.item});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('eBay Item Details')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 1. 이미지
            Center(
              child: item.imageUrl != null
                  ? ClipRRect(
                      borderRadius: BorderRadius.circular(12),
                      child: Image.network(
                        item.imageUrl!,
                        height: 250,
                        fit: BoxFit.cover,
                      ),
                    )
                  : const Icon(Icons.image_not_supported, size: 100, color: Colors.grey),
            ),
            const SizedBox(height: 24),

            // 2. 핵심 정보 카드
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16.0),
                child: Column(
                  children: [
                    _buildInfoRow('SKU', item.sku, isBold: true),
                    const Divider(),
                    _buildInfoRow('Title', item.title),
                    const Divider(),
                    _buildInfoRow('Quantity', '${item.quantity}'),
                    const Divider(),
                    _buildInfoRow('Condition', item.condition ?? 'N/A'),
                    if (item.groupId != null) ...[
                      const Divider(),
                      _buildInfoRow('Group ID', item.groupId!),
                    ]
                  ],
                ),
              ),
            ),
            const SizedBox(height: 24),

            // 3. 설명 (Description)
            const Text(
              "Description",
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.grey.shade100,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.grey.shade300),
              ),
              child: Text(
                item.description.isNotEmpty ? item.description : 'No description provided.',
                style: const TextStyle(fontSize: 14),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildInfoRow(String label, String value, {bool isBold = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 80,
            child: Text(
              label,
              style: const TextStyle(fontWeight: FontWeight.w600, color: Colors.grey),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: TextStyle(
                fontWeight: isBold ? FontWeight.bold : FontWeight.normal,
                fontSize: 15,
              ),
            ),
          ),
        ],
      ),
    );
  }
}