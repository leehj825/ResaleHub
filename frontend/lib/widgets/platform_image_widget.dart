import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';

// Conditional import for File on non-web platforms
import 'platform_image_widget_stub.dart'
    if (dart.library.io) 'platform_image_widget_io.dart' as io;

/// Widget that displays an image from a PlatformFile
/// Works on both web (using bytes) and mobile/desktop (using file path)
class PlatformImageWidget extends StatelessWidget {
  final PlatformFile file;
  final double? width;
  final double? height;
  final BoxFit fit;

  const PlatformImageWidget({
    super.key,
    required this.file,
    this.width,
    this.height,
    this.fit = BoxFit.cover,
  });

  @override
  Widget build(BuildContext context) {
    if (kIsWeb) {
      // Web: use Image.memory with bytes
      if (file.bytes != null) {
        return Image.memory(
          file.bytes!,
          width: width,
          height: height,
          fit: fit,
        );
      } else {
        return _buildPlaceholder();
      }
    } else {
      // Mobile/Desktop: use Image.file with path
      return io.buildImageFromPlatformFile(file, width: width, height: height, fit: fit);
    }
  }

  Widget _buildPlaceholder() {
    return Container(
      width: width,
      height: height,
      color: Colors.grey[300],
      child: const Icon(Icons.image, color: Colors.grey),
    );
  }
}
