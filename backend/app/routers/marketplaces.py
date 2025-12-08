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


#from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime

from app.core.config import get_settings
from app.core.database import get_db
from app.models.user import User
from app.models.marketplace_account import MarketplaceAccount

# ... 위쪽 생략 ...
settings = get_settings()

@router.get("/ebay/oauth/callback")
async def ebay_oauth_callback(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    eBay에서 redirect 될 때 콜백 URL

    - 쿼리의 state(=user id) 를 읽고
    - 그 유저의 MarketplaceAccount(ebay)를 생성/업데이트
    - 간단한 HTML을 돌려서 브라우저 탭 닫기
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        raise HTTPException(status_code=400, detail="Missing 'code' in callback")
    if not state:
        raise HTTPException(status_code=400, detail="Missing 'state' in callback")

    # 우리는 /ebay/connect 에서 state=current_user.id 로 보냈음
    try:
        user_id = int(state)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid state")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Unknown user")

    # 👉 지금은 token 교환은 생략하고, "연결됨" 플래그 용으로만 저장
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
            username=None,        # 나중에 eBay user id 넣을 수 있음
            access_token=None,    # 나중에 실제 토큰 저장
            refresh_token=None,
            token_expires_at=None,
        )
        db.add(account)
    else:
        # 기존 계정이 있으면 업데이트 시간만 갱신
        account.updated_at = datetime.utcnow()

    db.commit()

    # 브라우저 탭 닫아주는 간단 HTML
    html = """
    <html>
      <body>
        <p>eBay sandbox 연결이 완료되었습니다. 이 창을 닫고 앱으로 돌아가 주세요.</p>
        <script>
          window.close();
        </script>
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
    """
    Disconnect eBay account:
    - Remove customer's MarketplaceAccount entry for eBay
    - After this, /marketplaces/ebay/status returns connected: false
    """

    account = (
        db.query(MarketplaceAccount)
        .filter(
            MarketplaceAccount.user_id == current_user.id,
            MarketplaceAccount.marketplace == "ebay",
        )
        .first()
    )

    if not account:
        return {"message": "No eBay account was connected."}

    db.delete(account)
    db.commit()

    return {"message": "eBay account disconnected successfully."}
