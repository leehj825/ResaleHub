# app/services/ebay_client.py
from datetime import datetime, timedelta
import base64
import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.marketplace_account import MarketplaceAccount
from app.models.user import User
from app.routers import marketplaces  # EBAY_SCOPES 사용

settings = get_settings()


class EbayAuthError(Exception):
    pass


async def get_valid_ebay_access_token(db: Session, user: User) -> str:
    """
    - DB에서 유저의 eBay MarketplaceAccount 찾고
    - access_token이 아직 유효하면 그대로 반환
    - 만료되었고 refresh_token 있으면 새로 갱신 후 DB 저장
    """
    account = (
        db.query(MarketplaceAccount)
        .filter(
            MarketplaceAccount.user_id == user.id,
            MarketplaceAccount.marketplace == "ebay",
        )
        .first()
    )

    if not account or not account.access_token:
        raise EbayAuthError("eBay account not connected")

    now = datetime.utcnow()

    # 만료 5분 전까지는 그냥 사용
    if account.token_expires_at and account.token_expires_at > now + timedelta(minutes=5):
        return account.access_token

    # 여기까지 오면 refresh_token으로 갱신 시도
    if not account.refresh_token:
        raise EbayAuthError("No refresh_token for eBay account")

    token_url = (
        "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
        if settings.ebay_environment == "sandbox"
        else "https://api.ebay.com/identity/v1/oauth2/token"
    )

    raw = f"{settings.ebay_client_id}:{settings.ebay_client_secret}"
    basic = base64.b64encode(raw.encode("utf-8")).decode("utf-8")

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {basic}",
    }

    data = {
        "grant_type": "refresh_token",
        "refresh_token": account.refresh_token,
        "scope": " ".join(marketplaces.EBAY_SCOPES),
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(token_url, data=data, headers=headers)

    if resp.status_code != 200:
        raise EbayAuthError(
            f"Failed to refresh eBay token: {resp.status_code} {resp.text}"
        )

    token_json = resp.json()
    new_access_token = token_json.get("access_token")
    expires_in = token_json.get("expires_in", 7200)

    if not new_access_token:
        raise EbayAuthError("No access_token in refresh response")

    account.access_token = new_access_token
    account.token_expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))

    db.commit()
    db.refresh(account)

    return account.access_token


EBAY_API_BASE = (
    "https://api.sandbox.ebay.com"
    if settings.ebay_environment == "sandbox"
    else "https://api.ebay.com"
)


async def ebay_request(
    method: str,
    db: Session,
    user: User,
    path: str,
    params: dict | None = None,
    json: dict | None = None,
):
    """
    eBay REST 공통 요청 래퍼.
    - path 예: "/sell/inventory/v1/inventory_item/{sku}"
    """
    access_token = await get_valid_ebay_access_token(db, user)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Content-Language": "en-US",
    }

    url = EBAY_API_BASE + path

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json,
        )

    return resp


async def ebay_get(
    db: Session,
    user: User,
    path: str,
    params: dict | None = None,
):
    """
    eBay REST API GET용 간단 래퍼
    - path 예: "/sell/account/v1/fulfillment_policy"
    """
    return await ebay_request(
        method="GET",
        db=db,
        user=user,
        path=path,
        params=params,
        json=None,
    )


async def ebay_post(
    db: Session,
    user: User,
    path: str,
    json: dict | None = None,
    params: dict | None = None,
):
    """
    eBay REST API POST용 간단 래퍼
    - path 예: "/sell/inventory/v1/inventory_item/{sku}"
    """
    return await ebay_request(
        method="POST",
        db=db,
        user=user,
        path=path,
        params=params,
        json=json,
    )

async def ebay_put(
    db: Session,
    user: User,
    path: str,
    json: dict | None = None,
    params: dict | None = None,
):
    """
    eBay REST API PUT용 래퍼
    - 예: /sell/inventory/v1/inventory_item/{sku}
    """
    return await ebay_request(
        method="PUT",
        db=db,
        user=user,
        path=path,
        params=params,
        json=json,
    )


async def ebay_delete(
    db: Session,
    user: User,
    path: str,
    params: dict | None = None,
):
    """
    eBay REST API DELETE용 래퍼
    """
    return await ebay_request(
        method="DELETE",
        db=db,
        user=user,
        path=path,
        params=params,
        json=None,
    )
