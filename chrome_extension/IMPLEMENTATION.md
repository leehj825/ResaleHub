# Desktop-to-Cloud Authentication Implementation

## Overview
This implementation provides a Nifty-style pairing code flow for connecting Poshmark accounts from a desktop browser to the ResaleHub mobile app.

## Architecture

### 1. Chrome Extension (`/chrome_extension`)
- **manifest.json**: Manifest V3 configuration with cookie and activeTab permissions
- **popup.html**: Clean UI for entering pairing code
- **popup.js**: Logic to extract cookies and send to backend

### 2. Backend Endpoints (`/backend/app/routers/auth.py`)
- `POST /api/auth/pairing-code`: Generates 6-digit code for authenticated user
- `POST /api/auth/sync-extension`: Receives cookies + pairing code from extension
- `GET /api/auth/pairing-status/{code}`: Checks if cookies have been received

### 3. Flutter Screen (`/frontend/lib/screens/desktop_connection_screen.dart`)
- Displays pairing code
- Polls backend every 3 seconds for status
- Shows success animation when connected

## Database Model
New `PairingCode` model stores:
- 6-digit code
- User ID
- Expiration time (10 minutes)
- Status flags (is_used, cookies_received)

## Flow

1. **User opens Desktop Connection screen** in Flutter app
2. **Backend generates** 6-digit pairing code (expires in 10 min)
3. **User installs Chrome extension** and logs into poshmark.com
4. **User enters pairing code** in extension popup
5. **Extension extracts cookies** and sends to backend with code
6. **Backend validates code**, saves cookies to user's MarketplaceAccount
7. **Flutter app polls** status endpoint until success
8. **Success animation** shown, user navigated back

## Security Notes

- Pairing codes expire in 10 minutes
- Codes are single-use (marked as used after sync)
- Codes are user-specific (require authentication to generate)
- Cookies are stored encrypted in database
- Extension only works on poshmark.com domain

## Next Steps

1. Add icon files to chrome_extension folder (icon16.png, icon48.png, icon128.png)
2. Update BACKEND_URL in popup.js to your production URL
3. Test the full flow end-to-end
4. Consider adding rate limiting for pairing code generation
5. Add cleanup job to remove expired pairing codes periodically

