from typing import List
from urllib.parse import urlencode
import base64
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.listing import Listing
from app.models.listing_marketplace import ListingMarketplace
from app.models.marketplace_account import MarketplaceAccount

router = APIRouter(
    prefix="/marketplaces",
    tags=["marketplaces"],
)

settings = get_settings()


# --------------------------------------
# 공통: Listing 존재 + 소유권 검사
# --------------------------------------
def _get_owned_listing_or_404(listing_id: int, user: User, db: Session) -> Listing:
    listing = (
        db.query(Listing)
        .filter(Listing.id == listing_id, Listing.owner_id == user.id)
        .first()
    )
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return listing


# --------------------------------------
# 더미 publish 기록 생성 공통 함수
# --------------------------------------
def _create_dummy_publish(db: Session, listing: Listing, marketplace: str):
    existing = (
        db.query(ListingMarketplace)
        .filter(
            ListingMarketplace.listing_id == listing.id,
            ListingMarketplace.marketplace == marketplace,
        )
        .first()
    )
    if existing:
        return existing

    lm = ListingMarketplace(
        listing_id=listing.id,
        marketplace=marketplace,
        status="published",
        external_item_id=None,
        external_url=None,
    )
    db.add(lm)
    db.commit()
    db.refresh(lm)
    return lm


# --------------------------------------
# Dummy Publish — eBay
# --------------------------------------
@router.post("/ebay/{listing_id}/publish")
def publish_to_ebay(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    listing = _get_owned_listing_or_404(listing_id, current_user, db)
    lm = _create_dummy_publish(db, listing, "ebay")
    return lm


# --------------------------------------
# Dummy Publish — Poshmark
# --------------------------------------
@router.post("/poshmark/{listing_id}/publish")
def publish_to_poshmark(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    listing = _get_owned_listing_or_404(listing_id, current_user, db)
    lm = _create_dummy_publish(db, listing, "poshmark")
    return lm


# --------------------------------------
# 특정 Listing 이 어떤 마켓에 올라갔는지 조회
# --------------------------------------
@router.get("/listings/{listing_id}", response_model=List[str])
def get_listing_marketplaces(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = _get_owned_listing_or_404(listing_id, current_user, db)

    links = (
        db.query(ListingMarketplace)
        .filter(ListingMarketplace.listing_id == listing_id)
        .all()
    )

    return [link.marketplace for link in links]


# ============================================================
#                (신규) eBay OAuth: Step 1
# ============================================================
@router.get("/ebay/connect")
def ebay_connect(current_user: User = Depends(get_current_user)):
    """
    유저가 eBay 계정 연결하기 전에:
    eBay OAuth 로그인 URL을 만들어서 반환.
    """

    if not settings.ebay_client_id or not settings.ebay_redirect_uri:
        raise HTTPException(
            status_code=500,
            detail="eBay OAuth is not configured on the server"
        )

    params = {
        "client_id": settings.ebay_client_id,
        "redirect_uri": settings.ebay_redirect_uri,
        "response_type": "code",
        "scope": "https://api.ebay.com/oauth/api_scope",
        "state": str(current_user.id),  # 유저 ID 그대로 넣어서 콜백에서 복원
    }

    base_auth_url = (
        "https://auth.sandbox.ebay.com/oauth2/authorize"
        if settings.ebay_environment == "sandbox"
        else "https://auth.ebay.com/oauth2/authorize"
    )

    auth_url = f"{base_auth_url}?{urlencode(params)}"
    return {"auth_url": auth_url}


# ============================================================
#                (신규) eBay OAuth: Step 2 (callback)
# ============================================================
@router.get("/ebay/oauth/callback")
async def ebay_oauth_callback(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    eBay OAuth redirect callback
    지금은 테스트용: 받은 code/state를 그대로 돌려줌.
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        raise HTTPException(status_code=400, detail="Missing 'code' in callback")

    # 나중에:
    # - code -> access token 교환
    # - MarketplaceAccount 저장
    # 지금은 테스트용 정보만 반환
    return {
        "message": "eBay OAuth callback received",
        "state": state,
        "code": code,
    }
