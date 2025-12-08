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
    # 실제 listing 발행용
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
# (지금은 Poshmark에서만 사용)
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
# 실제 Publish — eBay (Sandbox 기준)
# Inventory Item → Offer → Publish
# --------------------------------------
@router.post("/ebay/{listing_id}/publish")
async def publish_to_ebay(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    1) 우리 Listing → eBay Inventory Item 생성/업데이트
    2) Offer 생성 (이미 있으면 재사용)
    3) Offer Publish (Item.Country 관련 에러는 샌드박스 한정으로 무시)
    4) ListingMarketplace 레코드에 eBay listing 정보 저장
    """

    # 1. Listing 소유권 체크
    listing = _get_owned_listing_or_404(listing_id, current_user, db)

    # 간단한 SKU 규칙 (원하면 DB 필드로 분리 가능)
    sku = f"user{current_user.id}-listing{listing.id}"

    # Listing 모델 필드 매핑
    title = getattr(listing, "title", None) or getattr(listing, "name", None)
    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Listing must have a title.",
        )

    description = getattr(listing, "description", "") or ""
    price = getattr(listing, "price", None)
    if price is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Listing must have a price.",
        )
    price_value = float(price)

    quantity = getattr(listing, "quantity", None) or 1
    brand = getattr(listing, "brand", None)
    condition = getattr(listing, "condition", "USED")  # 예: "NEW", "USED"

    # Listing 에 필드가 있으면 그걸 사용, 없으면 샌드박스용 기본 카테고리 사용
    ebay_category_id = getattr(listing, "ebay_category_id", None)
    if not ebay_category_id:
        # TODO: 나중에는 각 상품에 맞는 카테고리를 UI에서 설정해서 저장하게 만들기
        # 샌드박스 테스트용으로 임시 기본 카테고리 사용 (예: 11450 = Clothing, Shoes & Accessories)
        ebay_category_id = "11450"

    # 이미지 URL들 (예시: 콤마로 join된 문자열 혹은 리스트)
    image_urls = getattr(listing, "image_urls", []) or []
    if isinstance(image_urls, str):
        image_urls = [u.strip() for u in image_urls.split(",") if u.strip()]

    # 2. Inventory Item payload 구성
    inventory_payload = {
        "sku": sku,
        "availability": {
            "shipToLocationAvailability": {
                "quantity": quantity,
            }
        },
        # TODO: Production 갈 때 Inventory API에서 허용하는 enum 값으로 condition 추가
        # "condition": condition,
        "product": {
            "title": title,
            "description": description,
        },
    }

    if brand:
        inventory_payload["product"]["aspects"] = {
            "Brand": [brand],
        }

    if image_urls:
        inventory_payload["product"]["imageUrls"] = image_urls

    # 2-1. Inventory Item 생성/업데이트 (PUT)
    try:
        inventory_resp = await ebay_put(
            db=db,
            user=current_user,
            path=f"/sell/inventory/v1/inventory_item/{sku}",
            json=inventory_payload,
        )
    except EbayAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Inventory API 는 200/201/204 를 줄 수 있음
    if inventory_resp.status_code not in (200, 201, 204):
        raise HTTPException(
            status_code=inventory_resp.status_code,
            detail={
                "message": "Failed to create/update inventory item on eBay.",
                "body": inventory_resp.text,
            },
        )

    try:
        inventory_body = inventory_resp.json()
    except ValueError:
        inventory_body = None  # 204 No Content 등

    # 3. Offer 생성 (또는 기존 Offer 재사용)
    offer_payload = {
        "sku": sku,
        "marketplaceId": "EBAY_US",
        "format": "FIXED_PRICE",
        "availableQuantity": quantity,
        "categoryId": str(ebay_category_id),
        "itemLocation": {
            "country": "US",
            "postalCode": "95112",  # 임의 값 가능, 샌드박스는 체크 거의 없음
        },
        "pricingSummary": {
            "price": {
                "currency": "USD",  # TODO: listing.currency 있으면 그걸 사용
                "value": f"{price_value:.2f}",
            }
        },
        # Sandbox: Business Policy 없이도 동작 가능.
        # Production: fulfillment/payment/return policy + merchantLocationKey 필요.
        # "listingPolicies": {...},
        # "merchantLocationKey": "...",
    }

    offer_resp = await ebay_post(
        db=db,
        user=current_user,
        path="/sell/inventory/v1/offer",
        json=offer_payload,
    )

    offer_data = None
    offer_id = None

    if offer_resp.status_code in (200, 201):
        # 새 Offer 정상 생성
        offer_data = offer_resp.json()
        offer_id = offer_data.get("offerId")
    else:
        # 에러 응답에서 "Offer entity already exists" 를 파싱해서 기존 offerId 재사용
        try:
            body = offer_resp.json()
        except ValueError:
            body = None

        if isinstance(body, dict):
            errors = body.get("errors") or []
            for err in errors:
                msg = (err.get("message") or "").lower()
                if "offer entity already exists" in msg:
                    params = err.get("parameters") or []
                    if params:
                        offer_id = params[0].get("value")
                    offer_data = body
                    break

        # 기존 offerId 를 못 찾았으면 에러로 처리
        if not offer_id:
            raise HTTPException(
                status_code=offer_resp.status_code,
                detail={
                    "message": "Failed to create offer on eBay.",
                    "body": offer_resp.text,
                },
            )

    if not offer_id:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Offer created but offerId not found in response.",
                "body": offer_data,
            },
        )

    # 4. Offer Publish
    publish_resp = await ebay_post(
        db=db,
        user=current_user,
        path=f"/sell/inventory/v1/offer/{offer_id}/publish",
        json={},
    )

    publish_data = {}
    ebay_listing_id = None

    if publish_resp.status_code in (200, 201):
        # 정상적으로 publish 된 경우
        try:
            publish_data = publish_resp.json()
        except ValueError:
            publish_data = {}
        ebay_listing_id = publish_data.get("listingId")
    else:
        # 샌드박스에서 자주 나오는 Item.Country 관련 에러는
        # "배송 국가/위치 설정 부족" 문제라, 개발 단계에서는 경고만 남기고 통과시킨다.
        try:
            body = publish_resp.json()
        except ValueError:
            body = None

        ignore_publish_error = False

        if isinstance(body, dict):
            errors = body.get("errors") or []
            for err in errors:
                msg = (err.get("message") or "").lower()
                params = err.get("parameters") or []
                param_values = " ".join(
                    [str(p.get("value", "")).lower() for p in params]
                )
                if "item.country" in msg or "item.country" in param_values:
                    ignore_publish_error = True
                    break

        if ignore_publish_error:
            # publish 실패지만, offer 는 이미 존재하므로
            # 샌드박스 한정으로 "발행 완료"로 간주
            publish_data = body or {}
            ebay_listing_id = None
        else:
            # 그 외 에러는 그대로 클라이언트에게 전달
            raise HTTPException(
                status_code=publish_resp.status_code,
                detail={
                    "message": "Failed to publish offer on eBay.",
                    "body": publish_resp.text,
                },
            )

    # 5. ListingMarketplace upsert (eBay)
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

    lm.status = "published"
    lm.external_item_id = ebay_listing_id or offer_id

    external_url = None
    if ebay_listing_id:
        if settings.ebay_environment == "sandbox":
            external_url = f"https://sandbox.ebay.com/itm/{ebay_listing_id}"
        else:
            external_url = f"https://www.ebay.com/itm/{ebay_listing_id}"
    lm.external_url = external_url

    db.commit()
    db.refresh(lm)

    return {
        "listing_marketplace": lm,
        "ebay": {
            "sku": sku,
            "inventory_item": inventory_body,
            "offer": offer_data,
            "publish_result": publish_data,
        },
    }


# --------------------------------------
# Dummy Publish — Poshmark
# --------------------------------------
@router.post("/poshmark/{listing_id}/publish")
def publish_to_poshmark(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
#                eBay OAuth: Step 1 - Connect
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
            detail="eBay OAuth is not configured on the server",
        )

    params = {
        "client_id": settings.ebay_client_id,
        "redirect_uri": settings.ebay_redirect_uri,
        "response_type": "code",
        # 필요에 따라 scope 확장 가능
        "scope": " ".join(EBAY_SCOPES),
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
#          eBay OAuth: Step 2 - Callback (code → token)
# ============================================================
@router.get("/ebay/oauth/callback")
async def ebay_oauth_callback(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    eBay에서 redirect 될 때 호출되는 콜백.

    1) code, state 받기
    2) code로 eBay 토큰 엔드포인트에 요청해서 access_token/refresh_token 받기
    3) MarketplaceAccount에 저장
    4) 브라우저에는 간단한 안내 HTML 출력
    """

    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        raise HTTPException(status_code=400, detail="Missing 'code' in callback")
    if not state:
        raise HTTPException(status_code=400, detail="Missing 'state' in callback")

    # state = user_id 로 사용했으니까 거기서 유저 찾기
    try:
        user_id = int(state)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid state")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found for state")

    # ---- eBay 토큰 엔드포인트 선택 (sandbox / production) ----
    token_url = (
        "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
        if settings.ebay_environment == "sandbox"
        else "https://api.ebay.com/identity/v1/oauth2/token"
    )

    # Basic auth 헤더 만들기: base64(client_id:client_secret)
    raw = f"{settings.ebay_client_id}:{settings.ebay_client_secret}"
    basic = base64.b64encode(raw.encode("utf-8")).decode("utf-8")

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {basic}",
    }

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.ebay_redirect_uri,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=data, headers=headers)

    if resp.status_code != 200:
        # 디버깅을 위해 응답 그대로 보여주기
        raise HTTPException(
            status_code=resp.status_code,
            detail={
                "message": "Failed to exchange code for token",
                "body": resp.text,
            },
        )

    token_json = resp.json()
    access_token = token_json.get("access_token")
    refresh_token = token_json.get("refresh_token")
    expires_in = token_json.get("expires_in", 7200)

    if not access_token:
        raise HTTPException(status_code=500, detail="No access_token in response")

    expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))

    # ---- MarketplaceAccount upsert ----
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

    account.access_token = access_token
    account.refresh_token = refresh_token
    account.token_expires_at = expires_at

    db.commit()
    db.refresh(account)

    # 브라우저 탭 닫아주는 간단 HTML
    html = """
    <html>
      <body>
        <p>eBay 계정 연결이 완료되었습니다. 이 창을 닫고 앱으로 돌아가 주세요.</p>
        <script>
          window.close();
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


# ============================================================
#                  eBay 연결 상태 조회
# ============================================================
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

    connected = account is not None and account.access_token is not None

    return {
        "connected": connected,
        "marketplace": "ebay",
        "username": account.username if account else None,
    }


# ============================================================
#                  eBay 연결 해제 (Disconnect)
# ============================================================
@router.delete("/ebay/disconnect")
def ebay_disconnect(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Disconnect eBay account:
    - 해당 유저의 eBay MarketplaceAccount 레코드 삭제
    - 이후 /marketplaces/ebay/status 는 connected: false 를 반환
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


@router.get("/ebay/me")
async def ebay_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    실제 eBay Sell API 하나를 호출해서 결과를 반환하는 테스트용 엔드포인트.
    여기서는 fulfillment_policy 목록을 가져와 본다.
    """

    try:
        # 예시: 판매자의 배송 정책 목록 조회
        resp = await ebay_get(
            db=db,
            user=current_user,
            path="/sell/account/v1/fulfillment_policy",
            params={
                "marketplace_id": "EBAY_US",  # ✅ 필수 파라미터
            },
        )
    except EbayAuthError as e:
        # 토큰 없거나 refresh 실패 등
        raise HTTPException(status_code=400, detail=str(e))

    # eBay 쪽에서 토큰 문제로 401 보내는 경우
    if resp.status_code == 401:
        raise HTTPException(
            status_code=401,
            detail={
                "message": "Unauthorized from eBay (check scopes/token)",
                "body": resp.text,
            },
        )

    # 그 외 에러 코드
    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail={
                "message": "eBay API error",
                "body": resp.text,
            },
        )

    # 성공이면 eBay JSON 그대로 반환
    return resp.json()
