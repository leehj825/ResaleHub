import 'package:flutter/material.dart';
import 'package:frontend/models/ebay_item.dart';
import 'package:frontend/models/listing.dart';
import 'package:frontend/services/marketplace_service.dart';
import 'package:frontend/services/listing_service.dart';
import 'package:frontend/screens/ebay_item_detail_screen.dart'; // [필수] 상세화면 임포트

class EbayInventoryScreen extends StatefulWidget {
  const EbayInventoryScreen({super.key});

  @override
  State<EbayInventoryScreen> createState() => _EbayInventoryScreenState();
}

class _EbayInventoryScreenState extends State<EbayInventoryScreen> {
  final MarketplaceService _marketplaceService = MarketplaceService();
  final ListingService _listingService = ListingService(); // Import용 서비스
  
  List<EbayItem> _items = [];
  bool _isLoading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadInventory();
  }

  Future<void> _loadInventory() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final items = await _marketplaceService.getEbayInventory();
      if (!mounted) return;
      setState(() {
        _items = items;
        _isLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  // [기능 추가] eBay 아이템을 내 앱 인벤토리로 가져오기
  Future<void> _importItemToApp(EbayItem item) async {
    // 확인 팝업
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Import Item'),
        content: Text('Do you want to import "${item.title}" to your local inventory?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Import')),
        ],
      ),
    );

    if (confirm != true) return;

    try {
      // 1. eBay 정보를 바탕으로 로컬 Listing 객체 생성
      // 주의: Listing 모델에 맞는 필드만 채워넣음 (가격 정보가 eBay Inventory API에 없을 수 있어 0.0 처리)
      await _listingService.createListing(
        title: item.title,
        description: item.description.isNotEmpty ? item.description : "Imported from eBay SKU: ${item.sku}",
        price: 0.0, // Inventory API에는 가격이 별도 Offer에 있어서 일단 0으로 가져옴
        currency: "USD",
      );

      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Successfully imported to local inventory!')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to import: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('eBay Sandbox Inventory'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadInventory,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _loadInventory,
        child: _buildBody(),
      ),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.error_outline, color: Colors.red, size: 48),
              const SizedBox(height: 16),
              Text('Error: $_error', textAlign: TextAlign.center),
              const SizedBox(height: 16),
              ElevatedButton(onPressed: _loadInventory, child: const Text('Retry')),
            ],
          ),
        ),
      );
    }

    if (_items.isEmpty) {
      return ListView(
        children: const [
          SizedBox(height: 100),
          Center(child: Text('No items found in eBay Sandbox.')),
        ],
      );
    }

    return ListView.separated(
      padding: const EdgeInsets.all(12),
      itemCount: _items.length,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
      itemBuilder: (context, index) {
        final item = _items[index];
        return Card(
          elevation: 2,
          child: ListTile(
            contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            onTap: () {
              // [기능 추가] 탭하면 상세 화면으로 이동
              Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => EbayItemDetailScreen(item: item),
                ),
              );
            },
            leading: ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: SizedBox(
                width: 60,
                height: 60,
                child: item.imageUrl != null
                    ? Image.network(item.imageUrl!, fit: BoxFit.cover)
                    : Container(color: Colors.grey[200], child: const Icon(Icons.shopping_bag)),
              ),
            ),
            title: Text(item.title, maxLines: 1, overflow: TextOverflow.ellipsis),
            subtitle: Text('SKU: ${item.sku}\nQty: ${item.quantity}'),
            trailing: IconButton(
              icon: const Icon(Icons.download, color: Colors.blue),
              tooltip: "Import to App",
              onPressed: () => _importItemToApp(item), // [Import 버튼]
            ),
          ),
        );
      },
    );
  }
}