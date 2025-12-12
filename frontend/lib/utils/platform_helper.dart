// Platform helper that works on all platforms including web
import 'package:flutter/foundation.dart' show kIsWeb, defaultTargetPlatform;
import 'package:flutter/material.dart' show TargetPlatform;

/// Check if running on macOS (desktop only, not web)
bool get isMacOS {
  if (kIsWeb) return false;
  return defaultTargetPlatform == TargetPlatform.macOS;
}

/// Check if running on Windows (desktop only, not web)
bool get isWindows {
  if (kIsWeb) return false;
  return defaultTargetPlatform == TargetPlatform.windows;
}

/// Check if running on Linux (desktop only, not web)
bool get isLinux {
  if (kIsWeb) return false;
  return defaultTargetPlatform == TargetPlatform.linux;
}

/// Check if running on desktop (macOS, Windows, or Linux, but not web)
bool get isDesktop {
  if (kIsWeb) return false;
  return isMacOS || isWindows || isLinux;
}

