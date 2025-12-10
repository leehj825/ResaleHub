# ResaleHub
Resale Hub

## Render.com 배포 설정

### Playwright 브라우저 설치

Render.com에서 배포할 때는 빌드 명령어에 Playwright 브라우저 설치를 추가해야 합니다:

**Build Command:**
```bash
pip install -r requirements.txt && python -m playwright install chromium
```

또는 스크립트 사용:
```bash
pip install -r requirements.txt && bash install_playwright.sh
```

**Start Command:**
```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

### 환경 변수

Render.com 환경 변수 설정:
- `PLAYWRIGHT_BROWSERS_PATH=0` (선택사항, 시스템 경로 사용)
