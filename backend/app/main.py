from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import Base, engine
from app.routers import health, auth, listings

Base.metadata.create_all(bind=engine)

app = FastAPI(title="ResaleHub AI")

app.add_middleware(
    CORSMiddleware,          # ✅ 여기: 클래스만 넘긴다 (괄호 X)
    allow_origins=["*"],     # dev only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(listings.router)


@app.get("/")
def root():
    return {"message": "ResaleHub backend is running"}
