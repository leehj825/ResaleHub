from typing import List
from urllib.parse import urlencode, quote
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
    "https://api.ebay.com/oauth/api_scope", 
    "https://api.ebay.com/oauth/api_scope/sell.account.readonly", 
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
]

def _get_owned_listing_or_404(listing_id: int, user: User, db: Session) -> Listing:
    listing = (
        db.query(Listing)
        .filter(Listing.id == listing_id, Listing.owner_id == user.id)
        .first()
    )
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return listing

# ---------------------------------------------------------
# [FIX] Helper: Create/Ensure Merchant Location Exists
# ---------------------------------------------------------
async def _ensure_merchant_location(db: Session, user: User):
    """
    Ensures a 'merchant location' exists on eBay.
    This prevents Error 25002 (Item.Country missing).
    We use 'store_v3' to ensure a fresh, correct location key.
    """
    merchant_location_key = "store_v3" 
    
    # 1. Define Location Payload (San Jose, CA for Sandbox testing)
    location_payload = {
        "name": "Main Store",
        "location": {
            "address": {
                "addressLine1": "2055 Hamilton Ave",
                "city": "San Jose",
                "stateOrProvince": "CA",
                "postalCode": "95125",
                "country": "US" # [CRITICAL] Fixes Item.Country error
            }
        },
        "locationInstructions": "Ships from main warehouse",
        "merchantLocationStatus": "ENABLED",
        "locationTypes": ["STORE"]
    }

    # 2. Call API to Create/Update Location
    try:
        print(f">>> Creating Location: {merchant_location_key}")
        await ebay_post(
            db=db,
            user=user,
            path=f"/sell/inventory/v1/location/{merchant_location_key}",
            json=location_payload
        )
    except Exception as e:
        print(f"Warning during location check: {e}")

    return merchant_location_key

# --------------------------------------
# Sandbox Inventory View
# --------------------------------------
@router.get("/ebay/inventory")
async def ebay_inventory(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        resp = await ebay_get(
            db=db,
            user=current_user,
            path="/sell/inventory/v1/inventory_item",
            params={"limit": "100", "offset": "0"} 
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return resp.json()

# --------------------------------------
# Publish to eBay (Main Logic)
# --------------------------------------
@router.post("/ebay/{listing_id}/publish")
async def publish_to_ebay(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = _get_owned_listing_or_404(listing_id, current_user, db)

    # 1. Determine SKU (Sanitize input to avoid URL errors)
    raw_sku = listing.sku if (listing.sku and listing.sku.strip()) else f"USER{current_user.id}-LISTING{listing.id}"
    # Replace slashes/spaces which break URL paths like /inventory_item/1/001
    sku = raw_sku.strip().replace("/", "-").replace("\\", "-").replace(" ", "-")
    print(f">>> Publishing SKU: {sku}")

    # [FIX] Save SKU immediately to DB so it shows in app even if publish fails later
    if listing.sku != sku:
        listing.sku = sku
        db.add(listing)
        db.commit()
        db.refresh(listing)

    title = getattr(listing, "title", "Untitled")
    description = getattr(listing, "description", "No description") or "No description"
    price = float(getattr(listing, "price", 0) or 0)
    quantity = 1 
    
    # Sandbox Test Category
    ebay_category_id = "11450"

    # 2. Condition Mapping
    ebay_condition = "NEW"
    if listing.condition:
        c = listing.condition.lower()
        if "new" in c: ebay_condition = "NEW"
        elif "like" in c: ebay_condition = "LIKE_NEW"
        elif "good" in c or "used" in c: ebay_condition = "USED_GOOD"
        elif "parts" in c: ebay_condition = "FOR_PARTS_OR_NOT_WORKING"

    # Image Handling
    image_urls = []
    raw_images = getattr(listing, "image_urls", []) or []
    
    # Skip localhost images as eBay cannot access them
    if isinstance(raw_images, list):
        for img in raw_images:
            if isinstance(img, str) and img.startswith("http") and "127.0.0.1" not in img and "localhost" not in img:
                image_urls.append(img)

    # 3. [FIX] Ensure Merchant Location Exists (Solves Error 25002)
    merchant_location_key = await _ensure_merchant_location(db, current_user)

    # 4. Create Inventory Item (PUT)
    inventory_payload = {
        "sku": sku,
        "locale": "en_US", # [FIX] Required for Error 25702
        "product": {
            "title": title,
            "description": description,
            # "imageUrls": image_urls # Uncomment only if using public URLs
        },
        "condition": ebay_condition,
        "availability": {
            "shipToLocationAvailability": {
                "quantity": quantity
            }
        }
    }

    try:
        encoded_sku = quote(sku)
        inv_resp = await ebay_put(
            db=db,
            user=current_user,
            path=f"/sell/inventory/v1/inventory_item/{encoded_sku}",
            json=inventory_payload,
        )
    except EbayAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if inv_resp.status_code not in (200, 201, 204):
        print(f">>> Inventory Creation Failed: {inv_resp.text}")
        raise HTTPException(
            status_code=400, 
            detail={"message": "Failed to create Inventory Item", "ebay_resp": inv_resp.json()}
        )

    # 5. Create/Update Offer (POST/PUT)
    offer_payload = {
        "sku": sku,
        "marketplaceId": "EBAY_US",
        "format": "FIXED_PRICE",
        "availableQuantity": quantity,
        "categoryId": str(ebay_category_id),
        "listingDescription": description,
        "merchantLocationKey": merchant_location_key, # [FIX] Links offer to location
        "pricingSummary": {
            "price": {
                "currency": "USD",
                "value": f"{price:.2f}"
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
        # Check if offer already exists and reuse it
        try:
            body = offer_resp.json()
            for err in body.get("errors", []):
                if "offer entity already exists" in (err.get("message") or "").lower():
                    if err.get("parameters"):
                        offer_id = err["parameters"][0]["value"]
                    break
        except: pass
        
        if offer_id:
            # [FIX] Update existing offer with new location info
            print(f">>> Offer exists ({offer_id}). Updating...")
            await ebay_put(
                db=db,
                user=current_user,
                path=f"/sell/inventory/v1/offer/{offer_id}",
                json=offer_payload
            )
        else:
             print(f">>> Offer Creation Failed: {offer_resp.text}")
             raise HTTPException(status_code=400, detail={"message": "Offer creation failed", "ebay_resp": offer_resp.text})

    # 6. Publish Offer (POST)
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
        print(f">>> Publish Failed: {publish_resp.text}")
        raise HTTPException(status_code=400, detail={"message": "Publish failed", "ebay_resp": publish_resp.json()})

    # 7. Update DB
    lm = db.query(ListingMarketplace).filter(
        ListingMarketplace.listing_id == listing.id,
        ListingMarketplace.marketplace == "ebay"
    ).first()

    if not lm:
        lm = ListingMarketplace(listing_id=listing.id, marketplace="ebay")
        db.add(lm)

    lm.status = "published"
    lm.external_item_id = ebay_listing_id
    lm.sku = sku
    lm.offer_id = offer_id
    
    if ebay_listing_id:
        base_url = "https://sandbox.ebay.com/itm" if settings.ebay_environment == "sandbox" else "https://www.ebay.com/itm"
        lm.external_url = f"{base_url}/{ebay_listing_id}"

    db.commit()
    db.refresh(lm)

    return {
        "message": "Processed",
        "listing_id": ebay_listing_id,
        "url": lm.external_url
    }

# --------------------------------------
# OAuth & Utils
# --------------------------------------
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
    base = "https://auth.sandbox.ebay.com/oauth2/authorize" if settings.ebay_environment == "sandbox" else "https://auth.ebay.com/oauth2/authorize"
    return {"auth_url": f"{base}?{urlencode(params)}"}

@router.get("/ebay/oauth/callback")
async def ebay_oauth_callback(request: Request, db: Session = Depends(get_db)):
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state: raise HTTPException(status_code=400, detail="Missing code/state")
    try: user_id = int(state)
    except: raise HTTPException(status_code=400, detail="Invalid state")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(status_code=404, detail="User not found")

    token_url = "https://api.sandbox.ebay.com/identity/v1/oauth2/token" if settings.ebay_environment == "sandbox" else "https://api.ebay.com/identity/v1/oauth2/token"
    raw = f"{settings.ebay_client_id}:{settings.ebay_client_secret}"
    basic = base64.b64encode(raw.encode("utf-8")).decode("utf-8")
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            token_url, 
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": settings.ebay_redirect_uri},
            headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {basic}"}
        )
    
    if resp.status_code != 200: raise HTTPException(status_code=resp.status_code, detail=resp.text)
    
    token_json = resp.json()
    account = db.query(MarketplaceAccount).filter(MarketplaceAccount.user_id == user.id, MarketplaceAccount.marketplace == "ebay").first()
    if not account:
        account = MarketplaceAccount(user_id=user.id, marketplace="ebay")
        db.add(account)
    
    account.access_token = token_json.get("access_token")
    account.refresh_token = token_json.get("refresh_token")
    account.token_expires_at = datetime.utcnow() + timedelta(seconds=int(token_json.get("expires_in", 7200)))
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
    return {"message": "Poshmark publish not implemented yet"}

@router.get("/ebay/me")
async def ebay_me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        resp = await ebay_get(db=db, user=current_user, path="/sell/account/v1/fulfillment_policy", params={"marketplace_id": "EBAY_US"})
    except EbayAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return resp.json()