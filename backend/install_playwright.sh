#!/bin/bash
# Playwright 브라우저 설치 스크립트
# Render.com 빌드 시 자동 실행

echo "Installing Playwright browsers..."
python -m playwright install chromium
python -m playwright install-deps chromium || true  # 시스템 의존성 설치 (실패해도 계속)

echo "Playwright browsers installation complete."
