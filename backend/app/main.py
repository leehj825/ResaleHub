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


# --- [중요] Playwright 브라우저 확인 (서버 시작 시 실행) ---
@app.on_event("startup")
async def check_playwright_browsers():
    """
    Playwright 브라우저가 설치되어 있는지 확인합니다.
    Poshmark 자동화에 필요합니다.
    Render.com에서는 빌드 시점에 설치되어야 합니다.
    """
    try:
        from playwright.async_api import async_playwright
        
        print("=" * 60)
        print("--- Checking Playwright Browsers ---")
        async with async_playwright() as p:
            # 브라우저가 설치되어 있는지 확인
            try:
                browser = await p.chromium.launch(headless=True)
                await browser.close()
                print(">>> ✓ Playwright browsers are installed and working")
                print("=" * 60)
                return
            except Exception as e:
                error_msg = str(e)
                print(f">>> ✗ Playwright browser check failed: {error_msg}")
                
                if "Executable doesn't exist" in error_msg or "BrowserType.launch" in error_msg:
                    print(">>> Browser executable not found!")
                    print(">>> Attempting to install chromium...")
                    
                    import subprocess
                    import sys
                    import os
                    
                    try:
                        # Render.com 환경에서는 PLAYWRIGHT_BROWSERS_PATH를 설정하지 않음
                        env = os.environ.copy()
                        # Render.com의 경우 기본 경로 사용
                        
                        result = subprocess.run(
                            [sys.executable, "-m", "playwright", "install", "chromium"],
                            capture_output=True,
                            text=True,
                            timeout=300,  # 5분 타임아웃
                            env=env
                        )
                        
                        if result.returncode == 0:
                            print(">>> ✓ Playwright browsers installed successfully")
                            # 다시 확인
                            try:
                                browser = await p.chromium.launch(headless=True)
                                await browser.close()
                                print(">>> ✓ Browser verification successful")
                            except Exception as verify_error:
                                print(f">>> ✗ Browser verification failed: {verify_error}")
                        else:
                            print(f">>> ✗ Playwright install failed (code: {result.returncode})")
                            if result.stdout:
                                print(f">>> stdout: {result.stdout[:500]}")
                            if result.stderr:
                                print(f">>> stderr: {result.stderr[:500]}")
                            print(">>> For Render.com, add 'playwright install chromium' to build command")
                    except subprocess.TimeoutExpired:
                        print(">>> ✗ Playwright install timed out")
                        print(">>> Please add 'playwright install chromium' to Render.com build command")
                    except Exception as install_error:
                        print(f">>> ✗ Could not install Playwright: {install_error}")
                        print(">>> Please add 'playwright install chromium' to Render.com build command")
                else:
                    print(f">>> Unexpected Playwright error: {error_msg}")
        print("=" * 60)
    except ImportError:
        print(">>> Playwright not installed, skipping browser check")
    except Exception as e:
        print(f">>> Warning: Could not check Playwright browsers: {e}")
        print(">>> Please ensure 'playwright install chromium' is in Render.com build command")


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