from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text  # [추가됨] SQL 실행용

from app.core.config import get_settings
from app.core.database import Base, engine
from app.routers import health, auth, listings, listing_images, marketplaces

# --- Load settings ---
settings = get_settings()

# --- Create DB tables ---
Base.metadata.create_all(bind=engine)

# --- Create FastAPI app ---
app = FastAPI(title=settings.app_name)

# --- CORS (dev only) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # 개발용 (나중에 프론트 앱 주소로 제한 가능)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- [중요] DB 자동 패치 (서버 시작 시 실행) ---
# 기존 DB에 컬럼이 없어서 생기는 에러를 방지합니다.
@app.on_event("startup")
def fix_db_schema_startup():
    print("--- Checking Database Schema ---")
    with engine.connect() as conn:
        # 1. ListingMarketplace 테이블 패치 (기존)
        try:
            conn.execute(text("ALTER TABLE listing_marketplaces ADD COLUMN sku VARCHAR"))
            conn.commit()
            print(">>> ADDED COLUMN: listing_marketplaces.sku")
        except Exception:
            pass # 이미 존재하면 무시

        try:
            conn.execute(text("ALTER TABLE listing_marketplaces ADD COLUMN offer_id VARCHAR"))
            conn.commit()
            print(">>> ADDED COLUMN: listing_marketplaces.offer_id")
        except Exception:
            pass

        # 2. [신규] Listings 테이블에 sku, condition 추가
        try:
            conn.execute(text("ALTER TABLE listings ADD COLUMN sku VARCHAR(100)"))
            conn.commit()
            print(">>> ADDED COLUMN: listings.sku")
        except Exception:
            pass
        
        try:
            conn.execute(text("ALTER TABLE listings ADD COLUMN condition VARCHAR(50)"))
            conn.commit()
            print(">>> ADDED COLUMN: listings.condition")
        except Exception:
            pass
            
    print("--- Database Check Complete ---")


# --- [중요] Playwright 브라우저 자동 설치 (서버 시작 시 실행) ---
@app.on_event("startup")
async def install_playwright_browsers():
    """
    Playwright 브라우저가 설치되어 있지 않으면 자동으로 설치합니다.
    Poshmark 자동화에 필요합니다.
    """
    try:
        from playwright.async_api import async_playwright
        
        print("--- Checking Playwright Browsers ---")
        async with async_playwright() as p:
            # 브라우저가 설치되어 있는지 확인
            try:
                browser = await p.chromium.launch(headless=True)
                await browser.close()
                print(">>> Playwright browsers are already installed")
                return
            except Exception as e:
                error_msg = str(e)
                if "Executable doesn't exist" in error_msg or "BrowserType.launch" in error_msg:
                    # 브라우저가 없으면 설치
                    print(">>> Playwright browsers not found. Installing chromium...")
                    import subprocess
                    import sys
                    import os
                    
                    # playwright install 실행 (비동기로 실행하여 서버 시작을 블로킹하지 않음)
                    try:
                        result = subprocess.run(
                            [sys.executable, "-m", "playwright", "install", "chromium"],
                            capture_output=True,
                            text=True,
                            timeout=300,  # 5분 타임아웃
                            env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": "0"}  # 시스템 경로 사용
                        )
                        
                        if result.returncode == 0:
                            print(">>> Playwright browsers installed successfully")
                        else:
                            print(f">>> Warning: Playwright install had issues")
                            print(f">>> stdout: {result.stdout[:200]}")
                            print(f">>> stderr: {result.stderr[:200]}")
                            print(">>> You may need to run 'playwright install chromium' manually")
                    except subprocess.TimeoutExpired:
                        print(">>> Playwright install timed out. Please run 'playwright install chromium' manually")
                    except Exception as install_error:
                        print(f">>> Could not auto-install Playwright: {install_error}")
                        print(">>> Please run 'playwright install chromium' manually")
                else:
                    print(f">>> Unexpected Playwright error: {error_msg}")
    except ImportError:
        print(">>> Playwright not installed, skipping browser check")
    except Exception as e:
        print(f">>> Warning: Could not check Playwright browsers: {e}")
        print(">>> You may need to run 'playwright install chromium' manually")


# --- Routers ---
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(listings.router)
app.include_router(listing_images.router)
app.include_router(marketplaces.router)

# --- Static media files ---
app.mount(
    settings.media_url,                     # "/media"
    StaticFiles(directory=settings.media_root),  # backend/media
    name="media",
)

# --- Root endpoint ---
@app.get("/")
def root():
    return {"message": "ResaleHub backend is running"}