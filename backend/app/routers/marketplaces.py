from typing import List
from urllib.parse import urlencode
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
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
# eBay Publish (실제 저장 로직 포함)
# --------------------------------------
@router.post("/ebay/{listing_id}/publish")
def publish_to_ebay(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    listing = _get_owned_listing_or_404(listing_id, current_user, db)
    
    # 1. 기존에 발행된 기록이 있는지 확인
    lm = (
        db.query(ListingMarketplace)
        .filter(
            ListingMarketplace.listing_id == listing.id,
            ListingMarketplace.marketplace == "ebay",
        )
        .first()
    )

    if not lm:
        lm = ListingMarketplace(
            listing_id=listing.id,
            marketplace="ebay",
        )
        db.add(lm)

    # -------------------------------------------------------
    # [TODO] 여기에 실제 eBay API 호출 코드가 들어갑니다.
    # resp = ebay_client.publish_listing(...)
    # listing_id_ebay = resp['listingId']
    # -------------------------------------------------------
    
    # 2. (테스트용) API 호출 성공했다고 가정하고 DB 업데이트
    # 실제 eBay Sandbox 아이템 URL 형식
    fake_ebay_id = f"110550{listing.id}" # 임의의 ID 생성
    sandbox_url = f"https://www.sandbox.ebay.com/itm/{fake_ebay_id}"
    
    lm.status = "active"
    lm.external_item_id = fake_ebay_id
    lm.external_url = sandbox_url
    lm.sku = f"USER{current_user.id}-LISTING{listing.id}"
    lm.published_at = datetime.utcnow()

    db.commit()
    db.refresh(lm)
    
    return {
        "message": "Published to eBay (Simulation)",
        "listingId": lm.external_item_id,
        "url": lm.external_url
    }


# --------------------------------------
# Poshmark Publish (Dummy)
# --------------------------------------
@router.post("/poshmark/{listing_id}/publish")
def publish_to_poshmark(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    listing = _get_owned_listing_or_404(listing_id, current_user, db)
    
    lm = db.query(ListingMarketplace).filter(
        ListingMarketplace.listing_id==listing.id, 
        ListingMarketplace.marketplace=="poshmark"
    ).first()
    
    if not lm:
        lm = ListingMarketplace(
            listing_id=listing.id, 
            marketplace="poshmark",
            status="published",
            external_url="https://poshmark.com/listing/dummy-123"
        )
        db.add(lm)
        db.commit()
        db.refresh(lm)
        
    return lm


# --------------------------------------
# OAuth 관련 (기존 코드 유지)
# --------------------------------------
@router.get("/ebay/connect")
def ebay_connect(current_user: User = Depends(get_current_user)):
    if not settings.ebay_client_id or not settings.ebay_redirect_uri:
        # 설정이 없을 때 안전 장치
        return {"error": "eBay configuration missing"}

    params = {
        "client_id": settings.ebay_client_id,
        "redirect_uri": settings.ebay_redirect_uri,
        "response_type": "code",
        "scope": "https://api.ebay.com/oauth/api_scope https://api.ebay.com/oauth/api_scope/sell.inventory https://api.ebay.com/oauth/api_scope/sell.account.readonly", 
        "state": str(current_user.id),
    }

    base_auth_url = (
        "https://auth.sandbox.ebay.com/oauth2/authorize"
        if settings.ebay_environment == "sandbox"
        else "https://auth.ebay.com/oauth2/authorize"
    )

    auth_url = f"{base_auth_url}?{urlencode(params)}"
    return {"auth_url": auth_url}

@router.get("/ebay/oauth/callback")
async def ebay_oauth_callback(
    request: Request,
    db: Session = Depends(get_db),
):
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    try:
        user_id = int(state)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid state")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Unknown user")

    account = (
        db.query(MarketplaceAccount)
        .filter(
            MarketplaceAccount.user_id == user.id,
            MarketplaceAccount.marketplace == "ebay",
        )
        .first()
    )

    if not account:
        account = MarketplaceAccount(
            user_id=user.id,
            marketplace="ebay",
        )
        db.add(account)
    
    # 여기서는 토큰 교환 로직이 없으므로 시간만 갱신
    account.updated_at = datetime.utcnow()
    db.commit()

    html = """
    <html>
      <body>
        <h3 style="text-align:center; margin-top:50px;">eBay Connected!</h3>
        <p style="text-align:center;">You can close this window now.</p>
        <script>window.close();</script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)

@router.get("/ebay/status")
def ebay_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = (
        db.query(MarketplaceAccount)
        .filter(
            MarketplaceAccount.user_id == current_user.id,
            MarketplaceAccount.marketplace == "ebay",
        )
        .first()
    )
    return {
        "connected": account is not None,
        "marketplace": "ebay",
        "username": account.username if account else None,
    }

@router.delete("/ebay/disconnect")
def ebay_disconnect(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = (
        db.query(MarketplaceAccount)
        .filter(
            MarketplaceAccount.user_id == current_user.id,
            MarketplaceAccount.marketplace == "ebay",
        )
        .first()
    )
    if account:
        db.delete(account)
        db.commit()
    return {"message": "Disconnected"}
