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