import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:frontend/models/poshmark_item.dart';
import 'package:frontend/services/marketplace_service.dart';
import 'package:frontend/services/listing_service.dart';
import 'package:url_launcher/url_launcher.dart';

class PoshmarkInventoryScreen extends StatefulWidget {
  const PoshmarkInventoryScreen({super.key});

  @override
  State<PoshmarkInventoryScreen> createState() => _PoshmarkInventoryScreenState();
}

class _PoshmarkInventoryScreenState extends State<PoshmarkInventoryScreen> {
  final MarketplaceService _marketplaceService = MarketplaceService();
  final ListingService _listingService = ListingService(); 
  
  List<PoshmarkItem> _items = [];
  bool _isLoading = true;
  String? _error;
  String? _errorScreenshotBase64;
  String? _inventoryJobId;
  List<Map<String, dynamic>> _progressMessages = [];
  Timer? _progressTimer;
  bool _progressDialogOpen = false;

  @override
  void initState() {
    super.initState();
    _loadInventory();
  }

  @override
  void dispose() {
    _progressTimer?.cancel();
    super.dispose();
  }

  void _showProgressDialog() {
    if (_progressDialogOpen) return;
    _progressDialogOpen = true;

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => _ProgressDialogWidget(
        progressMessages: _progressMessages,
        onCancel: () {
          _progressTimer?.cancel();
          _progressDialogOpen = false;
          setState(() => _isLoading = false);
          Navigator.of(context).pop();
        },
      ),
    );
  }

  Future<void> _loadInventory() async {
    setState(() {
      _isLoading = true;
      _error = null;
      _progressMessages = [];
      _inventoryJobId = null;
    });

    _showProgressDialog(); // Show dialog immediately

    try {
      final jobId = await _marketplaceService.startPoshmarkInventoryFetch();
      if (!mounted) return;

      setState(() {
        _inventoryJobId = jobId;
      });

      _progressTimer = Timer.periodic(const Duration(seconds: 2), (timer) async {
        if (!mounted || _inventoryJobId == null) {
          timer.cancel();
          return;
        }

        try {
          final progress = await _marketplaceService.getPoshmarkInventoryProgress(_inventoryJobId!);
          if (!mounted) return;

          final status = progress['status'] as String;
          final messages = progress['messages'] as List<dynamic>;

          setState(() {
            _progressMessages = messages.map((m) => m as Map<String, dynamic>).toList();
          });

          // Update dialog by closing and reopening with new messages
          if (mounted && _progressDialogOpen && Navigator.of(context).canPop()) {
            Navigator.of(context).pop();
            _progressDialogOpen = false;
            _showProgressDialog();
          }

          if (status == 'completed' || status == 'failed') {
            timer.cancel();
            _progressDialogOpen = false;
            setState(() => _isLoading = false);

            if (mounted && Navigator.of(context).canPop()) {
              Navigator.of(context).pop();
            }

            if (status == 'completed') {
              final result = progress['result'] as Map<String, dynamic>?;
              if (result != null) {
                final List<dynamic> itemsJson = result['items'] ?? [];
                final items = itemsJson.map((json) => PoshmarkItem.fromJson(json)).toList();
                setState(() {
                  _items = items;
                  _error = null;
                  _errorScreenshotBase64 = null;
                });
              }
            } else {
              final latest = progress['latest_message'] as Map<String, dynamic>?;
              final errorMsg = latest?['message'] ?? 'Failed to load inventory';
              
              // Check if error has screenshot
              String? screenshotBase64;
              if (progress['result'] is Map<String, dynamic>) {
                final result = progress['result'] as Map<String, dynamic>;
                screenshotBase64 = result['screenshot'] as String?;
              }
              
              setState(() {
                _error = errorMsg;
                _errorScreenshotBase64 = screenshotBase64;
              });
            }
          }
        } catch (e) {
          debugPrint('Progress polling error: $e');
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _isLoading = false);
      if (Navigator.of(context).canPop()) {
        Navigator.of(context).pop(); // Close dialog
      }
      
      // Check if error has screenshot
      String? screenshotBase64;
      if (e is PoshmarkInventoryError) {
        screenshotBase64 = e.screenshotBase64;
      }
      
      setState(() {
        _error = e.toString();
        _errorScreenshotBase64 = screenshotBase64;
      });
    }
  }

  Future<void> _importItemToApp(PoshmarkItem item) async {
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
      await _listingService.createListing(
        title: item.title,
        description: "Imported from Poshmark",
        price: item.price,
        currency: "USD",
        sku: item.sku,
        importFrom: 'poshmark',
        thumbnailUrl: item.imageUrl,
      );

      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Successfully imported and linked to Poshmark!')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to import: $e')),
      );
    }
  }

  Future<void> _openInPoshmark(PoshmarkItem item) async {
    final uri = Uri.parse(item.url);
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    } else {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not open ${item.url}')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Poshmark Inventory'),
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
      return SingleChildScrollView(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.error_outline, color: Colors.red, size: 48),
                const SizedBox(height: 16),
                Text('Error: $_error', textAlign: TextAlign.center),
                if (_errorScreenshotBase64 != null) ...[
                  const SizedBox(height: 16),
                  const Text(
                    'Debug Screenshot:',
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 8),
                  Container(
                    decoration: BoxDecoration(
                      border: Border.all(color: Colors.grey),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: Image.memory(
                        base64Decode(_errorScreenshotBase64!),
                        fit: BoxFit.contain,
                        errorBuilder: (context, error, stackTrace) {
                          return const Padding(
                            padding: EdgeInsets.all(16.0),
                            child: Text('Failed to load screenshot'),
                          );
                        },
                      ),
                    ),
                  ),
                ],
                const SizedBox(height: 16),
                ElevatedButton(
                  onPressed: _loadInventory,
                  child: const Text('Retry'),
                ),
              ],
            ),
          ),
        ),
      );
    }

    if (_items.isEmpty) {
      return ListView(
        children: const [
          SizedBox(height: 100),
          Center(child: Text('No items found in Poshmark closet.')),
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
            onTap: () => _openInPoshmark(item),
            leading: ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: SizedBox(
                width: 60,
                height: 60,
                child: item.imageUrl != null && item.imageUrl!.isNotEmpty
                    ? Image.network(
                        item.imageUrl!, 
                        fit: BoxFit.cover,
                        errorBuilder: (ctx, err, stack) => Container(
                          color: Colors.grey[200], 
                          child: const Icon(Icons.broken_image, color: Colors.grey)
                        ),
                      )
                    : Container(
                        color: Colors.grey[200], 
                        child: const Icon(Icons.shopping_bag, color: Colors.grey)
                      ),
              ),
            ),
            title: Text(item.title, maxLines: 1, overflow: TextOverflow.ellipsis),
            subtitle: Text('SKU: ${item.sku}\nPrice: \$${item.price.toStringAsFixed(2)}'),
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                IconButton(
                  icon: const Icon(Icons.download, color: Colors.blue),
                  tooltip: "Import to App",
                  onPressed: () => _importItemToApp(item),
                ),
                IconButton(
                  icon: const Icon(Icons.open_in_new, color: Colors.green),
                  tooltip: "Open in Poshmark",
                  onPressed: () => _openInPoshmark(item),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _ProgressDialogWidget extends StatelessWidget {
  final List<Map<String, dynamic>> progressMessages;
  final VoidCallback onCancel;

  const _ProgressDialogWidget({
    required this.progressMessages,
    required this.onCancel,
  });

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Row(
        children: [
          SizedBox(
            width: 20,
            height: 20,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          SizedBox(width: 12),
          Text('Loading Poshmark Inventory...'),
        ],
      ),
      content: SizedBox(
        width: double.maxFinite,
        child: progressMessages.isEmpty
            ? const Text('Starting inventory fetch...')
            : ListView.builder(
                shrinkWrap: true,
                itemCount: progressMessages.length,
                itemBuilder: (context, index) {
                  final msg = progressMessages[index];
                  final message = msg['message'] as String? ?? '';
                  final level = msg['level'] as String? ?? 'info';

                  Color color;
                  IconData icon;
                  switch (level) {
                    case 'success':
                      color = Colors.green;
                      icon = Icons.check_circle;
                      break;
                    case 'error':
                      color = Colors.red;
                      icon = Icons.error;
                      break;
                    case 'warning':
                      color = Colors.orange;
                      icon = Icons.warning;
                      break;
                    default:
                      color = Colors.blue;
                      icon = Icons.info;
                  }

                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(icon, size: 16, color: color),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            message,
                            style: TextStyle(fontSize: 13, color: color),
                          ),
                        ),
                      ],
                    ),
                  );
                },
              ),
      ),
      actions: [
        TextButton(
          onPressed: onCancel,
          child: const Text('Cancel'),
        ),
      ],
    );
  }
}
