// ignore_for_file: unused_field

import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart'; // Clipboard
import 'package:url_launcher/url_launcher.dart';
import 'package:frontend/models/listing.dart';
import 'package:frontend/services/auth_service.dart';
import 'package:frontend/services/listing_service.dart' as ls;
import 'package:frontend/screens/edit_listing_screen.dart';

class ListingDetailScreen extends StatefulWidget {
  final Listing listing;

  const ListingDetailScreen({
    super.key,
    required this.listing,
  });

  @override
  State<ListingDetailScreen> createState() => _ListingDetailScreenState();
}

class _ListingDetailScreenState extends State<ListingDetailScreen> {
  final _authService = AuthService();
  final _listingService = ls.ListingService();

  late Listing _listing;
  bool _deleting = false;

  List<String> _imageUrls = [];
  bool _loadingImages = true;
  String? _imageError;

  bool _updatingStatus = false;
  bool _publishing = false;
  bool _preparingOffer = false;

  final List<String> _statusOptions = const ['draft', 'listed', 'sold'];

  @override
  void initState() {
    super.initState();
    _listing = widget.listing;
    _loadImages();
  }

  Future<void> _loadImages() async {
    setState(() {
      _loadingImages = true;
      _imageError = null;
    });

    try {
      final urls = await _listingService.getListingImages(_listing.id);
      if (!mounted) return;
      setState(() {
        _imageUrls = urls;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _imageError = e.toString();
      });
    } finally {
      if (!mounted) return;
      setState(() {
        _loadingImages = false;
      });
    }
  }

  Future<void> _reloadListing() async {
    try {
      final updated = await _listingService.getListing(_listing.id);
      if (!mounted) return;
      setState(() {
        _listing = updated;
      });
    } catch (e) {
      debugPrint('Failed to reload listing: $e');
    }
  }

  Future<void> _editListing() async {
    final updated = await Navigator.of(context).push<Listing>(
      MaterialPageRoute(
        builder: (_) => EditListingScreen(listing: _listing),
      ),
    );

    if (updated != null && mounted) {
      setState(() {
        _listing = updated;
      });
      _loadImages();
    }
  }

  Future<void> _deleteListing() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete Listing'),
        content: Text('Are you sure you want to delete "${_listing.title}"?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Delete', style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );

    if (confirmed != true) return;

    setState(() => _deleting = true);

    try {
      await _listingService.deleteListing(_listing.id);
      if (!mounted) return;
      Navigator.of(context).pop();
    } catch (e) {
      if (!mounted) return;
      setState(() => _deleting = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to delete: $e')),
      );
    }
  }

  Future<void> _deleteImage(String imageUrl) async {
    try {
      await _listingService.deleteListingImage(_listing.id, imageUrl);
      if (!mounted) return;
      setState(() {
        _imageUrls.remove(imageUrl);
      });
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to delete image: $e')),
      );
    }
  }

  Future<void> _changeStatus(String newStatus) async {
    if (newStatus == _listing.status || _updatingStatus) return;

    setState(() => _updatingStatus = true);

    try {
      final updated = await _listingService.updateListing(
        _listing.id,
        status: newStatus,
      );
      if (!mounted) return;
      setState(() => _listing = updated);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Status updated to "$newStatus"')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to update status: $e')),
      );
    } finally {
      if (!mounted) return;
      setState(() => _updatingStatus = false);
    }
  }

  Future<void> _publishToEbay() async {
    setState(() => _publishing = true);
    try {
      await _listingService.publishToEbay(_listing.id);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Published to eBay successfully!')),
      );
      await _reloadListing();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to publish to eBay: $e')),
      );
    } finally {
      if (mounted) setState(() => _publishing = false);
    }
  }

  Future<void> _prepareEbayOffer() async {
    setState(() => _preparingOffer = true);
    try {
      await _listingService.prepareEbayOffer(_listing.id);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Added to eBay inventory (offer staged, not published).')),
      );
      await _reloadListing();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to add to eBay inventory: $e')),
      );
    } finally {
      if (mounted) setState(() => _preparingOffer = false);
    }
  }

  String? _publishJobId;
  List<Map<String, dynamic>> _publishProgressMessages = [];
  Timer? _progressTimer;
  bool _progressDialogOpen = false;

  @override
  void dispose() {
    _progressTimer?.cancel();
    super.dispose();
  }

  Future<void> _publishToPoshmark() async {
    setState(() {
      _publishing = true;
      _publishProgressMessages = [];
      _publishJobId = null;
    });

    // Show progress dialog
    _showProgressDialog();

    try {
      // Start publish and get job ID
      final jobId = await _listingService.publishToPoshmark(_listing.id);
      if (!mounted) return;

      setState(() => _publishJobId = jobId);

      // Start polling for progress
      _progressTimer = Timer.periodic(const Duration(seconds: 2), (timer) async {
        if (!mounted || _publishJobId == null) {
          timer.cancel();
          return;
        }

        try {
          final progress = await _listingService.getPublishProgress(_publishJobId!);
          if (!mounted) return;

          final status = progress['status'] as String;
          final messages = progress['messages'] as List<dynamic>;

          setState(() {
            _publishProgressMessages = messages.map((m) => m as Map<String, dynamic>).toList();
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
            setState(() => _publishing = false);

            // Close dialog
            if (mounted && Navigator.of(context).canPop()) {
              Navigator.of(context).pop();
            }

            if (status == 'completed') {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Published to Poshmark successfully!')),
              );
              await _reloadListing();
            } else {
              final latest = progress['latest_message'] as Map<String, dynamic>?;
              final errorMsg = latest?['message'] ?? 'Publish failed';
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text('Failed to publish: $errorMsg')),
              );
            }
          }
        } catch (e) {
          debugPrint('Progress polling error: $e');
        }
      });
    } catch (e) {
      if (!mounted) return;
      _progressDialogOpen = false;
      setState(() => _publishing = false);
      if (Navigator.of(context).canPop()) {
        Navigator.of(context).pop(); // Close dialog
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to start publish: $e')),
      );
    }
  }

  void _showProgressDialog() {
    if (_progressDialogOpen) return;
    _progressDialogOpen = true;
    
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => _ProgressDialogWidget(
        progressMessages: _publishProgressMessages,
        onCancel: () {
          _progressTimer?.cancel();
          _progressDialogOpen = false;
          setState(() => _publishing = false);
          Navigator.of(context).pop();
        },
      ),
    );
    
    // Note: Dialog will be updated when setState is called with new progress messages
  }

  Widget _buildDetailRow(String label, String value, {bool copyable = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          SizedBox(
            width: 80,
            child: Text(label, style: const TextStyle(color: Colors.grey, fontWeight: FontWeight.w500, fontSize: 13)),
          ),
          Expanded(
            child: Text(value, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
          ),
          if (copyable)
            InkWell(
              onTap: () {
                Clipboard.setData(ClipboardData(text: value));
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('$label copied!'), duration: const Duration(seconds: 1)),
                );
              },
              child: const Padding(
                padding: EdgeInsets.only(left: 8.0),
                child: Icon(Icons.copy, size: 16, color: Colors.grey),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildMarketplaceSection() {
    // 1. eBay 정보
    final ebayInfo = _listing.marketplaces.firstWhere(
      (m) => m.marketplace == 'ebay',
      orElse: () => MarketplaceInfo(marketplace: '', status: ''),
    );
    
    bool isEbayPublished = (ebayInfo.listingUrl != null && ebayInfo.listingUrl!.isNotEmpty) || 
                           ebayInfo.status == 'published';
    bool isEbayInInventory = ebayInfo.status == 'offer_created' || ebayInfo.offerId != null;

    // 2. Poshmark 정보
    final poshInfo = _listing.marketplaces.firstWhere(
      (m) => m.marketplace == 'poshmark',
      orElse: () => MarketplaceInfo(marketplace: '', status: ''),
    );
    bool isPoshPublished = poshInfo.status == 'published';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          "Marketplace Integration",
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 12),

        if (_publishing)
          const Padding(
            padding: EdgeInsets.all(8.0),
            child: Center(child: CircularProgressIndicator()),
          ),

        Card(
          elevation: 2,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          child: Padding(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              children: [
                Row(
                  children: [
                    const Icon(Icons.shopping_bag_outlined, color: Colors.blue),
                    const SizedBox(width: 8),
                    const Text("eBay", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                    const Spacer(),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                        color: isEbayPublished 
                            ? Colors.green.shade100 
                            : isEbayInInventory 
                                ? Colors.blue.shade100 
                                : Colors.grey.shade200,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Text(
                        isEbayPublished 
                            ? "Published" 
                            : isEbayInInventory 
                                ? "In Inventory" 
                                : "Not Listed",
                        style: TextStyle(
                          color: isEbayPublished 
                              ? Colors.green.shade800 
                              : isEbayInInventory 
                                  ? Colors.blue.shade800 
                                  : Colors.grey.shade800,
                          fontSize: 12,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ],
                ),
                
                if (isEbayPublished || isEbayInInventory) ...[
                  const Divider(height: 24),
                  if (ebayInfo.externalItemId != null)
                    _buildDetailRow("Item ID", ebayInfo.externalItemId!, copyable: true),
                  
                  _buildDetailRow("SKU", ebayInfo.sku ?? _listing.sku ?? "N/A", copyable: true),
                  
                  // [UI 수정] Location 정보 표시 추가
                  _buildDetailRow("Location", "San Jose, US (Default)", copyable: false),

                  if (ebayInfo.offerId != null)
                    _buildDetailRow("Offer ID", ebayInfo.offerId!, copyable: true),
                  
                  const SizedBox(height: 16),
                  
                  if (ebayInfo.listingUrl != null)
                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton.icon(
                        onPressed: () async {
                          final uri = Uri.parse(ebayInfo.listingUrl!);
                          if (await canLaunchUrl(uri)) {
                            await launchUrl(uri, mode: LaunchMode.externalApplication);
                          }
                        },
                        icon: const Icon(Icons.open_in_new, color: Colors.white),
                        label: const Text("View on eBay Sandbox"),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.green,
                          foregroundColor: Colors.white,
                        ),
                      ),
                    )
                  else
                    const Text(
                      "Imported from inventory (URL unavailable)",
                      style: TextStyle(color: Colors.grey, fontStyle: FontStyle.italic),
                    ),
                ] else ...[
                  const SizedBox(height: 16),
                  Column(
                    children: [
                      SizedBox(
                        width: double.infinity,
                        child: OutlinedButton.icon(
                          onPressed: (_publishing || _preparingOffer) ? null : _prepareEbayOffer,
                          icon: const Icon(Icons.inventory_2_outlined),
                          label: const Text("Add to eBay (Inventory + Offer)"),
                        ),
                      ),
                      const SizedBox(height: 8),
                      SizedBox(
                        width: double.infinity,
                        child: ElevatedButton.icon(
                          onPressed: (_publishing || _preparingOffer) ? null : _publishToEbay,
                          icon: const Icon(Icons.upload),
                          label: const Text("Publish to eBay"),
                        ),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
        ),

        const SizedBox(height: 16),

        Card(
          elevation: 1,
          color: Colors.grey.shade50,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          child: ListTile(
            leading: const Icon(Icons.style_outlined, color: Colors.pinkAccent),
            title: const Text("Poshmark"),
            trailing: isPoshPublished
                ? const Icon(Icons.check_circle, color: Colors.green)
                : OutlinedButton(
                    onPressed: _publishing ? null : _publishToPoshmark,
                    child: const Text("List"),
                  ),
          ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final baseUrl = _authService.baseUrl;

    String? mainImageUrl;
    if (_imageUrls.isNotEmpty) {
      mainImageUrl = '$baseUrl${_imageUrls.first}';
    } else if (_listing.thumbnailUrl != null) {
      // [수정] 썸네일 URL 그대로 사용 (Import 시 저장된 외부 URL)
      mainImageUrl = _listing.thumbnailUrl;
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Listing Detail'),
        actions: [
          IconButton(icon: const Icon(Icons.edit), onPressed: _editListing),
          IconButton(icon: const Icon(Icons.delete_outline), onPressed: _deleting ? null : _deleteListing),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Center(
              child: mainImageUrl != null
                  ? ClipRRect(
                      borderRadius: BorderRadius.circular(12),
                      child: AspectRatio(
                        aspectRatio: 1,
                        child: Image.network(
                          mainImageUrl,
                          fit: BoxFit.cover,
                          errorBuilder: (c, e, s) => Container(color: Colors.grey.shade200, child: const Icon(Icons.broken_image)),
                        ),
                      ),
                    )
                  : Container(
                      width: double.infinity, height: 300,
                      decoration: BoxDecoration(color: Colors.grey.shade100, borderRadius: BorderRadius.circular(12)),
                      child: const Icon(Icons.image_not_supported, size: 64, color: Colors.grey),
                    ),
            ),
            const SizedBox(height: 16),

            if (_imageUrls.isNotEmpty)
              SizedBox(
                height: 80,
                child: ListView.builder(
                  scrollDirection: Axis.horizontal,
                  itemCount: _imageUrls.length,
                  itemBuilder: (context, index) {
                    final fullUrl = '$baseUrl${_imageUrls[index]}';
                    return Padding(
                      padding: const EdgeInsets.only(right: 8.0),
                      child: GestureDetector(
                        onTap: () => _deleteImage(_imageUrls[index]),
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(8),
                          child: Image.network(fullUrl, width: 80, height: 80, fit: BoxFit.cover),
                        ),
                      ),
                    );
                  },
                ),
              ),

            const SizedBox(height: 24),
            Text(_listing.title, style: theme.textTheme.headlineSmall),
            Text('${_listing.price.toStringAsFixed(2)} ${_listing.currency}',
                style: theme.textTheme.titleMedium?.copyWith(color: Colors.green, fontWeight: FontWeight.bold)),
            
            const SizedBox(height: 16),

            // SKU & Condition 표시
            if (_listing.sku != null || _listing.condition != null) ...[
              Row(
                children: [
                  if (_listing.sku != null)
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text("SKU", style: theme.textTheme.labelMedium?.copyWith(color: Colors.grey)),
                          const SizedBox(height: 4),
                          SelectableText(_listing.sku!, style: const TextStyle(fontWeight: FontWeight.bold)),
                        ],
                      ),
                    ),
                  if (_listing.condition != null)
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text("Condition", style: theme.textTheme.labelMedium?.copyWith(color: Colors.grey)),
                          const SizedBox(height: 4),
                          Text(_listing.condition!, style: const TextStyle(fontWeight: FontWeight.bold)),
                        ],
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 16),
            ],

            Text('Status', style: theme.textTheme.titleMedium),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: _statusOptions.map((status) {
                final isSelected = _listing.status == status;
                return ChoiceChip(
                  label: Text(status),
                  selected: isSelected,
                  onSelected: _updatingStatus
                      ? null
                      : (selected) {
                          if (selected) _changeStatus(status);
                        },
                );
              }).toList(),
            ),
            if (_updatingStatus)
              const Padding(padding: EdgeInsets.only(top: 8.0), child: LinearProgressIndicator()),

            const SizedBox(height: 24),
            const Divider(),
            
            _buildMarketplaceSection(),

            const Divider(),
            const SizedBox(height: 16),
            Text('Description', style: theme.textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(_listing.description ?? 'No description', style: theme.textTheme.bodyMedium),
            const SizedBox(height: 40),
          ],
        ),
      ),
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
          Text('Publishing to Poshmark...'),
        ],
      ),
      content: SizedBox(
        width: double.maxFinite,
        child: progressMessages.isEmpty
            ? const Text('Starting publish...')
            : ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 400),
                child: ListView.builder(
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
                              softWrap: true,
                              overflow: TextOverflow.visible,
                            ),
                          ),
                        ],
                      ),
                    );
                  },
                ),
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