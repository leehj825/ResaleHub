import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../models/listing.dart';
import '../services/listing_service.dart';
import '../widgets/platform_image_widget.dart';

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

  // [추가] 상태(Condition) 선택용 기본값
  String _selectedCondition = 'New with Tags'; 
  
  // Condition 옵션들 (사용자 친화적인 이름)
  final List<String> _conditionOptions = [
    'New with Tags',
    'New without Tags',
    'Pre-owned',
    'For Parts or Not Working'
  ];

  bool _saving = false;
  String? _error;

  final _listingService = ListingService();

  // 선택된 이미지들
  List<PlatformFile> _selectedImages = [];

  Future<void> _pickImages() async {
    setState(() {
      _error = null;
    });

    try {
      // 파일 선택기 실행 (다중 선택 가능)
      final result = await FilePicker.platform.pickFiles(
        allowMultiple: true,
        type: FileType.image,
      );

      if (result != null && result.files.isNotEmpty) {
        setState(() {
          _selectedImages = result.files;
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = 'Failed to pick images: $e';
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

      // 1) Listing 생성 요청 (SKU, Condition 포함)
      final listing = await _listingService.createListing(
        title: _titleController.text.trim(),
        description: _descriptionController.text.trim().isEmpty
            ? null
            : _descriptionController.text.trim(),
        price: price,
        // 입력된 SKU가 없으면 null을 보내 백엔드에서 자동 생성하게 함
        sku: _skuController.text.trim().isEmpty ? null : _skuController.text.trim(),
        condition: _selectedCondition,
      );

      // 2) 이미지가 선택되어 있다면 업로드
      if (_selectedImages.isNotEmpty) {
        await _listingService.uploadImages(listing.id, _selectedImages);
      }

      if (!mounted) return;
      // 목록 화면으로 돌아가면서 생성된 객체 전달 (목록 새로고침용)
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
    _skuController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('New Listing'),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Title
            TextField(
              controller: _titleController,
              decoration: const InputDecoration(
                labelText: 'Title',
                hintText: 'e.g., Samsung Galaxy S25',
              ),
            ),
            const SizedBox(height: 12),
            
            // Description
            TextField(
              controller: _descriptionController,
              maxLines: 3,
              decoration: const InputDecoration(
                labelText: 'Description',
                hintText: 'Describe the item condition, features, etc.',
              ),
            ),
            const SizedBox(height: 12),
            
            // Price & SKU Row
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _priceController,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: const InputDecoration(
                      labelText: 'Price (USD)',
                      hintText: '0.00',
                    ),
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: TextField(
                    controller: _skuController,
                    decoration: const InputDecoration(
                      labelText: 'SKU (Optional)',
                      hintText: 'Auto-generated if empty',
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),

            // Condition Dropdown
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

            // Image Picker
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

            // Image Preview (Horizontal Scroll)
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
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(8),
                        child: PlatformImageWidget(
                          file: _selectedImages[index],
                          width: 80,
                          height: 80,
                          fit: BoxFit.cover,
                        ),
                      ),
                    );
                  },
                ),
              ),
            ],

            const SizedBox(height: 24),

            // Error Message
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(
                  _error!,
                  style: theme.textTheme.bodyMedium?.copyWith(color: Colors.red),
                ),
              ),

            // Save Button
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: _saving ? null : _save,
                style: ElevatedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  backgroundColor: theme.primaryColor,
                  foregroundColor: Colors.white,
                  disabledBackgroundColor: Colors.grey[400],
                  disabledForegroundColor: Colors.white,
                ),
                child: _saving
                    ? Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                            ),
                          ),
                          const SizedBox(width: 12),
                          const Text('Saving...', style: TextStyle(fontSize: 16)),
                        ],
                      )
                    : const Text('Save', style: TextStyle(fontSize: 16)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}