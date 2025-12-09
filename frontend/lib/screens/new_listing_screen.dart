import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../models/listing.dart';
import '../services/listing_service.dart';

class NewListingScreen extends StatefulWidget {
  const NewListingScreen({super.key});

  @override
  State<NewListingScreen> createState() => _NewListingScreenState();
}

class _NewListingScreenState extends State<NewListingScreen> {
  final _titleController = TextEditingController();
  final _descriptionController = TextEditingController();
  final _priceController = TextEditingController();
  final _skuController = TextEditingController(); // [추가] SKU 입력용

  // [추가] 상태(Condition) 선택용 변수
  String _selectedCondition = 'Used'; 
  final List<String> _conditionOptions = [
    'New',
    'Like New',
    'Used',
    'For Parts'
  ];

  bool _saving = false;
  String? _error;

  final _listingService = ListingService();

  // 선택된 이미지들
  List<File> _selectedImages = [];

  Future<void> _pickImages() async {
    setState(() {
      _error = null;
    });

    try {
      final result = await FilePicker.platform.pickFiles(
        allowMultiple: true,
        type: FileType.image,
      );

      if (result != null && result.files.isNotEmpty) {
        setState(() {
          _selectedImages = result.files
              .where((f) => f.path != null)
              .map((f) => File(f.path!))
              .toList();
        });
      } else {
        // 선택 취소
        debugPrint('User canceled picking files');
      }
    } catch (e, st) {
      debugPrint('File picker error: $e');
      debugPrint(st.toString());
      if (!mounted) return;
      setState(() {
        _error = 'Failed to open file picker: $e';
      });
    }
  }


  Future<void> _save() async {
    setState(() {
      _saving = true;
      _error = null;
    });

    try {
      final price = double.tryParse(_priceController.text.trim()) ?? 0.0;

      // 1) Listing 생성 (SKU, Condition 포함)
      final listing = await _listingService.createListing(
        title: _titleController.text.trim(),
        description: _descriptionController.text.trim().isEmpty
            ? null
            : _descriptionController.text.trim(),
        price: price,
        // [추가] 입력된 SKU와 선택된 Condition 전달
        sku: _skuController.text.trim().isEmpty ? null : _skuController.text.trim(),
        condition: _selectedCondition,
      );

      // 2) 이미지가 선택되어 있다면 업로드
      if (_selectedImages.isNotEmpty) {
        await _listingService.uploadImages(listing.id, _selectedImages);
      }

      if (!mounted) return;
      // ListingsScreen으로 listing을 넘겨서 reload 트리거
      Navigator.of(context).pop<Listing>(listing);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
      });
    } finally {
      if (!mounted) return;
      setState(() {
        _saving = false;
      });
    }
  }

  @override
  void dispose() {
    _titleController.dispose();
    _descriptionController.dispose();
    _priceController.dispose();
    _skuController.dispose(); // [추가] 해제
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('New Listing'),
      ),
      body: SingleChildScrollView( // 스크롤 가능하게 변경
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: _titleController,
              decoration: const InputDecoration(labelText: 'Title'),
            ),
            const SizedBox(height: 12),
            
            TextField(
              controller: _descriptionController,
              maxLines: 3,
              decoration: const InputDecoration(labelText: 'Description'),
            ),
            const SizedBox(height: 12),
            
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _priceController,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: const InputDecoration(labelText: 'Price (USD)'),
                  ),
                ),
                const SizedBox(width: 16),
                // [추가] SKU 입력 필드
                Expanded(
                  child: TextField(
                    controller: _skuController,
                    decoration: const InputDecoration(labelText: 'SKU (Optional)'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),

            // [추가] Condition 드롭다운
            DropdownButtonFormField<String>(
              value: _selectedCondition,
              decoration: const InputDecoration(labelText: 'Condition'),
              items: _conditionOptions.map((String condition) {
                return DropdownMenuItem<String>(
                  value: condition,
                  child: Text(condition),
                );
              }).toList(),
              onChanged: (String? newValue) {
                if (newValue != null) {
                  setState(() {
                    _selectedCondition = newValue;
                  });
                }
              },
            ),

            const SizedBox(height: 24),

            // 이미지 선택 버튼 + 개수 표시
            Row(
              children: [
                ElevatedButton.icon(
                  onPressed: _saving ? null : _pickImages,
                  icon: const Icon(Icons.photo_library),
                  label: const Text('Select Photos'),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    _selectedImages.isEmpty
                        ? 'No photos selected'
                        : '${_selectedImages.length} photo(s) selected',
                    style: theme.textTheme.bodyMedium,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),

            // 선택된 이미지 미리보기 (작게)
            if (_selectedImages.isNotEmpty) ...[
              const SizedBox(height: 10),
              SizedBox(
                height: 80,
                child: ListView.builder(
                  scrollDirection: Axis.horizontal,
                  itemCount: _selectedImages.length,
                  itemBuilder: (context, index) {
                    return Padding(
                      padding: const EdgeInsets.only(right: 8.0),
                      child: Image.file(
                        _selectedImages[index],
                        width: 80,
                        height: 80,
                        fit: BoxFit.cover,
                      ),
                    );
                  },
                ),
              ),
            ],

            const SizedBox(height: 24),

            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(
                  _error!,
                  style: theme.textTheme.bodyMedium?.copyWith(color: Colors.red),
                ),
              ),

            _saving
                ? const Center(child: CircularProgressIndicator())
                : SizedBox(
                    width: double.infinity,
                    child: ElevatedButton(
                      onPressed: _save,
                      style: ElevatedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        backgroundColor: theme.primaryColor,
                        foregroundColor: Colors.white,
                      ),
                      child: const Text('Save Listing', style: TextStyle(fontSize: 16)),
                    ),
                  ),
          ],
        ),
      ),
    );
  }
}