from typing import List
from urllib.parse import urlencode
import base64
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.listing import Listing
from app.models.listing_marketplace import ListingMarketplace
from app.models.marketplace_account import MarketplaceAccount

from app.services.ebay_client import ebay_get, ebay_post, ebay_put, EbayAuthError

router = APIRouter(
    prefix="/marketplaces",
    tags=["marketplaces"],
)

settings = get_settings()

EBAY_SCOPES = [
    "https://api.ebay.com/oauth/api_scope",  # 기본
    "https://api.ebay.com/oauth/api_scope/sell.account.readonly",  # 계정 정책 조회용
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
]


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
# Sandbox Inventory 조회 (디버깅용)
# --------------------------------------
@router.get("/ebay/inventory")
async def ebay_inventory(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        # limit=100 추가하여 페이징 문제 해결
        resp = await ebay_get(
            db=db,
            user=current_user,
            path="/sell/inventory/v1/inventory_item",
            params={"limit": "100", "offset": "0"} 
        )
    except Exception as e:
        print(f"Error calling ebay_get: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code, 
            detail={"message": "Failed to fetch inventory", "body": resp.text}
        )

    return resp.json()


# --------------------------------------
# 실제 Publish — eBay (Sandbox 기준)
# Inventory Item → Offer → Publish
# --------------------------------------
@router.post("/ebay/{listing_id}/publish")
async def publish_to_ebay(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1. Listing 소유권 체크
    listing = _get_owned_listing_or_404(listing_id, current_user, db)

    sku = f"user{current_user.id}-listing{listing.id}"

    title = getattr(listing, "title", None) or getattr(listing, "name", None)
    if not title:
        raise HTTPException(status_code=400, detail="Listing must have a title.")

    description = getattr(listing, "description", "") or "No description"
    price = getattr(listing, "price", None)
    if price is None:
        raise HTTPException(status_code=400, detail="Listing must have a price.")
    price_value = float(price)

    quantity = 1 # 기본값
    
    # eBay 기본 카테고리 (Sandbox 테스트용 - 의류/신발/액세서리)
    ebay_category_id = "11450" 

    image_urls = getattr(listing, "image_urls", []) or []
    # 단순 문자열 리스트로 변환 (객체인 경우 처리)
    final_image_urls = []
    if isinstance(image_urls, list):
        for img in image_urls:
            if isinstance(img, str):
                final_image_urls.append(img)
            elif hasattr(img, "file_path"): # DB 객체인 경우
                # 실제 운영환경에선 전체 URL(https://...)이 필요함. 
                # 로컬호스트 URL은 eBay가 접근 못하므로 여기선 비워두거나 S3 URL 사용 권장.
                pass 

    # [필수] Condition 설정 (없으면 NEW)
    # eBay Enum: NEW, LIKE_NEW, USED_EXCELLENT, USED_VERY_GOOD, USED_GOOD, USED_ACCEPTABLE
    ebay_condition = "NEW" 
    if listing.condition:
        c = listing.condition.lower()
        if "used" in c:
            ebay_condition = "USED_GOOD"
        elif "new" in c:
            ebay_condition = "NEW"
    
    # ---------------------------------------------------------
    # Step 1. Inventory Item 생성/업데이트 (PUT)
    # [수정] locale과 condition이 반드시 있어야 함!
    # ---------------------------------------------------------
    inventory_payload = {
        "sku": sku,
        "locale": "en_US", # [필수] 이거 없으면 Error 25702 발생
        "product": {
            "title": title,
            "description": description,
            # "imageUrls": final_image_urls 
        },
        "condition": ebay_condition, # [필수]
        "availability": {
            "shipToLocationAvailability": {
                "quantity": quantity
            }
        }
    }

    try:
        inv_resp = await ebay_put(
            db=db,
            user=current_user,
            path=f"/sell/inventory/v1/inventory_item/{sku}",
            json=inventory_payload,
        )
    except EbayAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Inventory 생성 실패 확인
    if inv_resp.status_code not in (200, 201, 204):
        raise HTTPException(
            status_code=400, 
            detail={
                "message": "Failed to create Inventory Item on eBay",
                "ebay_response": inv_resp.json() if inv_resp.content else inv_resp.text
            }
        )

    # ---------------------------------------------------------
    # Step 2. Offer 생성
    # ---------------------------------------------------------
    offer_payload = {
        "sku": sku,
        "marketplaceId": "EBAY_US",
        "format": "FIXED_PRICE",
        "availableQuantity": quantity,
        "categoryId": str(ebay_category_id),
        "listingDescription": description,
        "itemLocation": {
            "country": "US",
            "postalCode": "95125", # San Jose Zip
        },
        "pricingSummary": {
            "price": {
                "currency": "USD",
                "value": f"{price_value:.2f}"
            }
        },
    }

    offer_resp = await ebay_post(
        db=db,
        user=current_user,
        path="/sell/inventory/v1/offer",
        json=offer_payload,
    )

    offer_id = None
    if offer_resp.status_code in (200, 201):
        offer_id = offer_resp.json().get("offerId")
    else:
        # 이미 존재하는 Offer 재사용
        try:
            body = offer_resp.json()
            errors = body.get("errors", [])
            for err in errors:
                if "offer entity already exists" in (err.get("message") or "").lower():
                    params = err.get("parameters", [])
                    if params:
                        offer_id = params[0].get("value")
                    break
        except:
            pass
        
        if not offer_id:
             raise HTTPException(status_code=400, detail=f"Offer creation failed: {offer_resp.text}")

    # ---------------------------------------------------------
    # Step 3. Publish
    # ---------------------------------------------------------
    publish_resp = await ebay_post(
        db=db,
        user=current_user,
        path=f"/sell/inventory/v1/offer/{offer_id}/publish",
        json={},
    )

    ebay_listing_id = None
    if publish_resp.status_code in (200, 201):
        ebay_listing_id = publish_resp.json().get("listingId")
    else:
        # Publish 실패 시 에러 처리
        # (샌드박스 설정 문제로 인한 Item.Country 에러 등은 무시 가능하지만 여기선 엄격하게 처리)
        raise HTTPException(status_code=400, detail=f"Publish failed: {publish_resp.text}")

    # ---------------------------------------------------------
    # Step 4. DB 저장
    # ---------------------------------------------------------
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
            marketplace=marketplace,
        )
        db.add(lm)

    lm.status = "published" if ebay_listing_id else "offer_created"
    lm.external_item_id = ebay_listing_id
    lm.sku = sku
    lm.offer_id = offer_id

    if ebay_listing_id:
        base_url = "https://sandbox.ebay.com/itm" if settings.ebay_environment == "sandbox" else "https://www.ebay.com/itm"
        lm.external_url = f"{base_url}/{ebay_listing_id}"
    else:
        lm.external_url = None

    db.commit()
    db.refresh(lm)

    return {
        "message": "Processed",
        "listing_id": ebay_listing_id,
        "url": lm.external_url
    }

# ============================================================
#                eBay OAuth & Utils
# ============================================================
@router.get("/ebay/connect")
def ebay_connect(current_user: User = Depends(get_current_user)):
    if not settings.ebay_client_id or not settings.ebay_redirect_uri:
        raise HTTPException(status_code=500, detail="eBay OAuth config missing")

    params = {
        "client_id": settings.ebay_client_id,
        "redirect_uri": settings.ebay_redirect_uri,
        "response_type": "code",
        "scope": " ".join(EBAY_SCOPES),
        "state": str(current_user.id),
    }
    base_auth_url = "https://auth.sandbox.ebay.com/oauth2/authorize" if settings.ebay_environment == "sandbox" else "https://auth.ebay.com/oauth2/authorize"
    return {"auth_url": f"{base_auth_url}?{urlencode(params)}"}

@router.get("/ebay/oauth/callback")
async def ebay_oauth_callback(request: Request, db: Session = Depends(get_db)):
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code/state")

    try:
        user_id = int(state)
    except:
        raise HTTPException(status_code=400, detail="Invalid state")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    token_url = "https://api.sandbox.ebay.com/identity/v1/oauth2/token" if settings.ebay_environment == "sandbox" else "https://api.ebay.com/identity/v1/oauth2/token"
    
    raw = f"{settings.ebay_client_id}:{settings.ebay_client_secret}"
    basic = base64.b64encode(raw.encode("utf-8")).decode("utf-8")

    headers = {"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {basic}"}
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": settings.ebay_redirect_uri}

    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=data, headers=headers)

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    token_json = resp.json()
    account = db.query(MarketplaceAccount).filter(MarketplaceAccount.user_id == user.id, MarketplaceAccount.marketplace == "ebay").first()
    if not account:
        account = MarketplaceAccount(user_id=user.id, marketplace="ebay")
        db.add(account)

    account.access_token = token_json.get("access_token")
    account.refresh_token = token_json.get("refresh_token")
    expires_in = token_json.get("expires_in", 7200)
    account.token_expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))

    db.commit()
    
    return HTMLResponse(content="<html><body><p>eBay Connected! Close this window.</p><script>window.close();</script></body></html>")

@router.get("/ebay/status")
def ebay_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = db.query(MarketplaceAccount).filter(MarketplaceAccount.user_id == current_user.id, MarketplaceAccount.marketplace == "ebay").first()
    return {"connected": account is not None and account.access_token is not None, "marketplace": "ebay"}

@router.delete("/ebay/disconnect")
def ebay_disconnect(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = db.query(MarketplaceAccount).filter(MarketplaceAccount.user_id == current_user.id, MarketplaceAccount.marketplace == "ebay").first()
    if account:
        db.delete(account)
        db.commit()
    return {"message": "Disconnected"}

@router.get("/listings/{listing_id}", response_model=List[str])
def get_listing_marketplaces(listing_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _get_owned_listing_or_404(listing_id, current_user, db)
    links = db.query(ListingMarketplace).filter(ListingMarketplace.listing_id == listing_id).all()
    return [link.marketplace for link in links]

@router.post("/poshmark/{listing_id}/publish")
def publish_to_poshmark(listing_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    listing = _get_owned_listing_or_404(listing_id, current_user, db)
    lm = _create_dummy_publish(db, listing, "poshmark")
    return lm

@router.get("/ebay/me")
async def ebay_me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        resp = await ebay_get(db=db, user=current_user, path="/sell/account/v1/fulfillment_policy", params={"marketplace_id": "EBAY_US"})
    except EbayAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail={"message": "eBay API error", "body": resp.text})
    return resp.json()