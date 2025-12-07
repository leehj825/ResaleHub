import 'package:flutter/material.dart';

import 'package:frontend/models/listing.dart';
import 'package:frontend/services/listing_service.dart';
import 'package:frontend/screens/new_listing_screen.dart';

class ListingsScreen extends StatefulWidget {
  const ListingsScreen({super.key});

  @override
  State<ListingsScreen> createState() => _ListingsScreenState();
}

class _ListingsScreenState extends State<ListingsScreen> {
  final _listingService = ListingService();
  bool _loading = true;
  String? _error;
  List<Listing> _listings = [];

  @override
  void initState() {
    super.initState();
    _loadListings();
  }

  Future<void> _loadListings() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final items = await _listingService.getMyListings();
      if (!mounted) return;
      setState(() {
        _listings = items;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
      });
    } finally {
      if (!mounted) return;
      setState(() {
        _loading = false;
      });
    }
  }

  Future<void> _openNewListing() async {
    final created = await Navigator.of(context).push<Listing>(
      MaterialPageRoute(builder: (_) => const NewListingScreen()),
    );

    if (created != null) {
      // 새로 생성됐으면 리스트 다시 로드
      _loadListings();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('My Listings'),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Text('Error: $_error'))
              : _listings.isEmpty
                  ? const Center(child: Text('No listings yet.'))
                  : ListView.builder(
                      itemCount: _listings.length,
                      itemBuilder: (context, index) {
                        final item = _listings[index];
                        return ListTile(
                          title: Text(item.title),
                          subtitle: Text(
                            '${item.price.toStringAsFixed(2)} ${item.currency} • ${item.status}',
                          ),
                        );
                      },
                    ),
      floatingActionButton: FloatingActionButton(
        onPressed: _openNewListing,
        child: const Icon(Icons.add),
      ),
    );
  }
}
