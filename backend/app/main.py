from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
