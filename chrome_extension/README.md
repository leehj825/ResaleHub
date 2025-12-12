# ResaleHub Chrome Extension

Chrome Extension for syncing Poshmark cookies to ResaleHub using a pairing code flow.

## Installation

1. Open Chrome and navigate to `chrome://extensions/`
2. Enable "Developer mode" (toggle in top right)
3. Click "Load unpacked"
4. Select the `chrome_extension` folder
5. The extension icon should appear in your toolbar

## Configuration

Before using, update the `BACKEND_URL` in `popup.js` to point to your backend:

```javascript
const BACKEND_URL = 'https://your-backend-url.com';
```

## Usage

1. Log in to poshmark.com in your browser
2. Click the ResaleHub extension icon
3. Enter the 6-digit pairing code from your mobile app
4. Click "Sync Poshmark Cookies"
5. Wait for success confirmation

## Icons

You'll need to add icon files:
- `icon16.png` (16x16 pixels)
- `icon48.png` (48x48 pixels)
- `icon128.png` (128x128 pixels)

You can create simple icons or use placeholder images for now.

