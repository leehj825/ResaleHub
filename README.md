# ResaleHub — Reviewed README

This document is a consolidated developer guide and short code-review summary for the repository.

## Project layout

- `backend/` : FastAPI backend with SQLAlchemy models, routers, and marketplace integrations.
- `frontend/` : Flutter app (mobile/desktop/web) that consumes the backend API.

---

## Backend — Run (development)

1. Create and activate a Python virtual environment:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

3. Provide environment variables:

 - For Render hosting: save your environment variables in the Render service dashboard (do not store secrets in the repo).
 - For local development: create `backend/.env` yourself with the required variables (the repository does not include an example file).

4. Start dev server:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API: `http://127.0.0.1:8000` — media is mounted under `/media`.

Notes:
- The app currently runs `Base.metadata.create_all(...)` on startup which is fine for local dev. For production use Alembic migrations.
- Restrict CORS origins in production (`backend/app/main.py`).

---

## Frontend — Run (development)

Prerequisites: Install Flutter SDK and any platform toolchains you need.

1. Get dependencies:

```bash
cd frontend
flutter pub get
```

2. Run on a target platform:

```bash
# web (Chrome)
flutter run -d chrome

# macOS desktop
flutter run -d macos

# Android emulator
flutter run -d emulator-5554
```

The frontend's API base URL is currently set in `frontend/lib/services/auth_service.dart`. For local development update it to point to `http://127.0.0.1:8000` or make the service read a configurable value.

---

## Poshmark Connect — System Browser Bookmarklet (Quick Guide)

Use the system-browser connect flow to avoid WebView-related bot detection. The backend exposes a small bookmarklet helper that copies `document.cookie` on poshmark.com and posts it to the connect page.

1. In the app `Settings` screen, tap **Connect Poshmark**. The app opens a system browser to a short-lived connect URL (valid ~10 minutes).
2. Sign in to poshmark.com in that browser tab.
3. Open the bookmarklet (drag the provided 'Copy Poshmark Cookies & Open Connect' link to your bookmarks bar while on the connect page or copy the JS from the textarea and create a bookmark manually). Then, while on a signed-in poshmark.com page, click the bookmarklet. It will open the connect page and automatically send cookies via `postMessage`.
4. Back in the app, the Settings screen will poll the backend for connection status and notify you when the account is connected.

Security notes:
- The connect URL contains a short-lived token (not your user id). The token expires in 10 minutes and is consumed on use.
- Only run the bookmarklet on your own device and do not store the bookmarklet on shared machines.
- If you prefer a more locked-down flow, we can add one-time nonce verification and require HTTPS-only origins for the connect page.


---

## Render.com (deployment notes)

If you use Playwright in production (usually not required), install browsers during build. Example Build & Start commands on Render:

```bash
pip install -r requirements.txt && python -m playwright install chromium

uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Set `PLAYWRIGHT_BROWSERS_PATH=0` to use system browsers (optional).

---

## Code Review Summary (concise)

I reviewed the backend and frontend code and summarize the top findings and recommended fixes below.

### High-priority issues
- **Circular import**: `backend/app/services/ebay_client.py` imports `app.routers.marketplaces` (for `EBAY_SCOPES`) and `marketplaces.py` imports `ebay_client`. Move `EBAY_SCOPES` into a neutral module like `backend/app/core/constants.py`.
- **Sync DB in async code**: Async functions in `ebay_client.py` perform synchronous SQLAlchemy operations (`db.query`, `db.commit`). These will block the event loop. Options: run DB calls in a threadpool (`run_in_threadpool`), change the endpoint to sync, or adopt an async DB layer.
- **Frontend web breakage**: `frontend/lib/services/auth_service.dart` imports `dart:io` unguarded. That prevents web builds. Use `kIsWeb` and conditional imports; prefer a cross-platform storage approach.
- **Media path mismatch**: `ListingImage.file_path` appears to be stored with `media/...` in comments, while thumbnail generation prefixes `settings.media_url`, which may result in `/media/media/...`. Store DB file paths relative to the media root (e.g., `listings/1/abc.jpg`).

### Medium-priority issues
- Replace direct `Base.metadata.create_all` with Alembic migrations for production.
- Document required env vars and ensure secrets are stored in the deployment environment (Render) or in a local `backend/.env` not checked into git.
- Review `requirements.txt` and split dev vs runtime deps (e.g., `playwright` may be dev-only).

### Suggestions / next steps
- Add CI running `pytest`/`flutter analyze` and linters (ruff/black for Python, dart format/lints for Flutter).
- Add structured logging and a standard API error response format for the frontend to parse.

---

## Quick Developer Tasks (recommended immediate fixes)

1. Move `EBAY_SCOPES` out of `marketplaces.py` into `backend/app/core/constants.py`.
2. Avoid sync DB calls in async functions (`ebay_client.py`) — either run DB ops in a threadpool or make them sync.
3. Change `frontend/lib/services/auth_service.dart` to avoid `dart:io` in web builds and standardize token storage.
4. Add Alembic and create initial migrations.

---

## Useful commands

```bash
# Search for dart:io usage (frontend)
cd frontend
rg "dart:io|\bPlatform\b" || true

# Search for EBAY_SCOPES / ebay_client usage (backend)
cd backend
rg "EBAY_SCOPES|ebay_client|marketplaces" || true

# Run backend
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload

# Run frontend
cd frontend
flutter pub get
flutter analyze
flutter run -d chrome
```

---

If you'd like I can apply the immediate fixes (move constants, adjust DB usage, update frontend storage). Tell me which to prioritize and I will create the patches.
