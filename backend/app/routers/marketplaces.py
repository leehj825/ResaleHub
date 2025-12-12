# backend/app/routers/marketplaces.py

# [FIX] 필수 타입 및 Body 임포트 추가
from typing import List, Dict, Any, Optional
from urllib.parse import urlencode, quote
import base64
import re
import json
import traceback # 에러 디버깅용
from datetime import datetime, timedelta
import secrets

import httpx
# [FIX] Body 임포트 추가
from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, Body, BackgroundTasks
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.listing import Listing
from app.models.listing_image import ListingImage
from app.models.listing_marketplace import ListingMarketplace
from app.models.marketplace_account import MarketplaceAccount
from app.models.connect_token import ConnectToken

from app.services.ebay_client import ebay_get, ebay_post, ebay_put, ebay_delete, EbayAuthError
from app.services.poshmark_client import (
    publish_listing as poshmark_publish_listing,
    PoshmarkAuthError,
    PoshmarkPublishError,
    verify_poshmark_cookie,
)
import logging

router = APIRouter(
    prefix="/marketplaces",
    tags=["marketplaces"],
)

settings = get_settings()

EBAY_SCOPES = [
    "https://api.ebay.com/oauth/api_scope", 
    "https://api.ebay.com/oauth/api_scope/sell.account.readonly", 
    "https://api.ebay.com/oauth/api_scope/sell.account",
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

def _sanitize_sku(raw_sku: str) -> str:
    sanitized = re.sub(r'[^a-zA-Z0-9_/-]', '-', raw_sku)
    sanitized = re.sub(r'-+', '-', sanitized)
    sanitized = sanitized.strip('-').strip('_')
    if not sanitized:
        sanitized = "SKU"
    return sanitized

# ---------------------------------------------------------
# eBay Helpers
# ---------------------------------------------------------
async def _ensure_business_policies_opted_in(db: Session, user: User) -> bool:
    try:
        programs_resp = await ebay_get(
            db=db,
            user=user,
            path="/sell/account/v1/program/get_opted_in_programs"
        )
        
        if programs_resp.status_code == 200:
            programs_data = programs_resp.json()
            programs = programs_data.get("programs", [])
            for program in programs:
                if program.get("programType") == "SELLING_POLICY_MANAGEMENT":
                    return True
            
            opt_in_resp = await ebay_post(
                db=db,
                user=user,
                path="/sell/account/v1/program/opt_in",
                json={"programType": "SELLING_POLICY_MANAGEMENT"}
            )
            
            if opt_in_resp.status_code in (200, 201, 204):
                return True
            return False
        else:
            return False
    except Exception as e:
        print(f">>> Error checking/opting into Business Policies: {e}")
        return False

async def _create_default_policies(db: Session, user: User):
    policies_created = {}
    try:
        shipping_services_to_try = ["USPSGroundAdvantage", "USPSFirstClass", "USPSPriorityMail"]
        for svc_code in shipping_services_to_try:
            fulfillment_payload = {
                "name": f"Standard Shipping ({svc_code})",
                "marketplaceId": "EBAY_US",
                "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
                "handlingTime": {"value": 1, "unit": "DAY"},
                "shippingOptions": [{
                    "optionType": "DOMESTIC",
                    "costType": "FLAT_RATE",
                    "shippingServices": [{
                        "shippingCarrierCode": "USPS",
                        "shippingServiceCode": svc_code,
                        "freeShipping": False
                    }]
                }]
            }
            fulfillment_resp = await ebay_post(db=db, user=user, path="/sell/account/v1/fulfillment_policy", json=fulfillment_payload)
            if fulfillment_resp.status_code in (200, 201):
                policies_created["fulfillmentPolicyId"] = fulfillment_resp.json().get("fulfillmentPolicyId")
                break
            else:
                error_body = fulfillment_resp.json()
                if "already exists" in str(error_body).lower():
                    existing = await ebay_get(db=db, user=user, path="/sell/account/v1/fulfillment_policy", params={"marketplace_id": "EBAY_US"})
                    if existing.status_code == 200 and existing.json().get("fulfillmentPolicies"):
                        policies_created["fulfillmentPolicyId"] = existing.json()["fulfillmentPolicies"][0]["fulfillmentPolicyId"]
                        break

        if "fulfillmentPolicyId" not in policies_created:
             existing = await ebay_get(db=db, user=user, path="/sell/account/v1/fulfillment_policy", params={"marketplace_id": "EBAY_US"})
             if existing.status_code == 200 and existing.json().get("fulfillmentPolicies"):
                 policies_created["fulfillmentPolicyId"] = existing.json()["fulfillmentPolicies"][0]["fulfillmentPolicyId"]

        payment_payload = {
            "name": "Standard Payment",
            "marketplaceId": "EBAY_US",
            "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
            "immediatePay": False
        }
        payment_resp = await ebay_post(db=db, user=user, path="/sell/account/v1/payment_policy", json=payment_payload)
        if payment_resp.status_code in (200, 201):
            policies_created["paymentPolicyId"] = payment_resp.json().get("paymentPolicyId")
        elif "already exists" in str(payment_resp.json()).lower():
             existing = await ebay_get(db=db, user=user, path="/sell/account/v1/payment_policy", params={"marketplace_id": "EBAY_US"})
             if existing.status_code == 200 and existing.json().get("paymentPolicies"):
                 policies_created["paymentPolicyId"] = existing.json()["paymentPolicies"][0]["paymentPolicyId"]
        
        if "paymentPolicyId" not in policies_created:
             existing = await ebay_get(db=db, user=user, path="/sell/account/v1/payment_policy", params={"marketplace_id": "EBAY_US"})
             if existing.status_code == 200 and existing.json().get("paymentPolicies"):
                 policies_created["paymentPolicyId"] = existing.json()["paymentPolicies"][0]["paymentPolicyId"]

        return_payload = {
            "name": "30-Day Returns",
            "marketplaceId": "EBAY_US",
            "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
            "returnsAccepted": True,
            "returnPeriod": {"value": 30, "unit": "DAY"},
            "refundMethod": "MONEY_BACK",
            "returnShippingCostPayer": "BUYER"
        }
        return_resp = await ebay_post(db=db, user=user, path="/sell/account/v1/return_policy", json=return_payload)
        if return_resp.status_code in (200, 201):
            policies_created["returnPolicyId"] = return_resp.json().get("returnPolicyId")
        elif "already exists" in str(return_resp.json()).lower():
             existing = await ebay_get(db=db, user=user, path="/sell/account/v1/return_policy", params={"marketplace_id": "EBAY_US"})
             if existing.status_code == 200 and existing.json().get("returnPolicies"):
                 policies_created["returnPolicyId"] = existing.json()["returnPolicies"][0]["returnPolicyId"]
        
        if "returnPolicyId" not in policies_created:
             existing = await ebay_get(db=db, user=user, path="/sell/account/v1/return_policy", params={"marketplace_id": "EBAY_US"})
             if existing.status_code == 200 and existing.json().get("returnPolicies"):
                 policies_created["returnPolicyId"] = existing.json()["returnPolicies"][0]["returnPolicyId"]

        if len(policies_created) == 3:
            return policies_created
        return None
    except Exception as e:
        print(f">>> Error creating default policies: {e}")
        return None

async def _get_ebay_policies(db: Session, user: User):
    try:
        override_policy_ids = {}
        if getattr(settings, "ebay_fulfillment_policy_id", None): override_policy_ids["fulfillmentPolicyId"] = settings.ebay_fulfillment_policy_id
        if getattr(settings, "ebay_payment_policy_id", None): override_policy_ids["paymentPolicyId"] = settings.ebay_payment_policy_id
        if getattr(settings, "ebay_return_policy_id", None): override_policy_ids["returnPolicyId"] = settings.ebay_return_policy_id
        if len(override_policy_ids) == 3: return override_policy_ids

        fulfillment_resp = await ebay_get(db=db, user=user, path="/sell/account/v1/fulfillment_policy", params={"marketplace_id": "EBAY_US"})
        payment_resp = await ebay_get(db=db, user=user, path="/sell/account/v1/payment_policy", params={"marketplace_id": "EBAY_US"})
        return_resp = await ebay_get(db=db, user=user, path="/sell/account/v1/return_policy", params={"marketplace_id": "EBAY_US"})
        
        fulfillment_policies = fulfillment_resp.json().get("fulfillmentPolicies", []) if fulfillment_resp.status_code == 200 else []
        payment_policies = payment_resp.json().get("paymentPolicies", []) if payment_resp.status_code == 200 else []
        return_policies = return_resp.json().get("returnPolicies", []) if return_resp.status_code == 200 else []
        
        def get_policy_id(policies, key="fulfillmentPolicyId"):
            if not policies: return None
            for p in policies:
                if "default" in p.get("name", "").lower() or "standard" in p.get("name", "").lower(): return p.get(key)
            return policies[0].get(key)
        
        fulfillment_policy_id = get_policy_id(fulfillment_policies, "fulfillmentPolicyId")
        payment_policy_id = get_policy_id(payment_policies, "paymentPolicyId")
        return_policy_id = get_policy_id(return_policies, "returnPolicyId")

        if not fulfillment_policy_id: fulfillment_policy_id = getattr(settings, "ebay_fulfillment_policy_id", None)
        if not payment_policy_id: payment_policy_id = getattr(settings, "ebay_payment_policy_id", None)
        if not return_policy_id: return_policy_id = getattr(settings, "ebay_return_policy_id", None)
        
        if fulfillment_policy_id and payment_policy_id and return_policy_id:
            return {"fulfillmentPolicyId": fulfillment_policy_id, "paymentPolicyId": payment_policy_id, "returnPolicyId": return_policy_id}
        else:
            opted_in = await _ensure_business_policies_opted_in(db, user)
            if not opted_in: return None
            return await _create_default_policies(db, user)
            
    except Exception as e:
        print(f">>> Warning: Failed to fetch eBay policies: {e}")
        return None

async def _ensure_merchant_location(db: Session, user: User):
    merchant_location_key = "store_v3"
    location_payload = {
        "name": "Main Store",
        "location": {
            "address": {
                "addressLine1": "2055 Hamilton Ave",
                "city": "San Jose",
                "stateOrProvince": "CA",
                "postalCode": "95125",
                "country": "US"
            }
        },
        "locationInstructions": "Ships from main warehouse",
        "merchantLocationStatus": "ENABLED",
        "locationTypes": ["STORE"]
    }
    try:
        await ebay_post(db=db, user=user, path=f"/sell/inventory/v1/location/{merchant_location_key}", json=location_payload)
    except: pass
    return merchant_location_key

# --------------------------------------
# eBay Endpoints
# --------------------------------------
@router.get("/ebay/inventory")
async def ebay_inventory(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        resp = await ebay_get(db=db, user=current_user, path="/sell/inventory/v1/inventory_item", params={"limit": "100", "offset": "0"})
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))
    return resp.json()

@router.delete("/ebay/inventory/{sku}")
async def delete_ebay_inventory_item(sku: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        resp = await ebay_delete(db=db, user=current_user, path=f"/sell/inventory/v1/inventory_item/{quote(sku)}")
    except EbayAuthError as e: raise HTTPException(status_code=400, detail=str(e))
    if resp.status_code not in (200, 204): raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return {"message": "Deleted", "sku": sku}

@router.post("/ebay/sync-inventory")
async def sync_ebay_inventory(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        resp = await ebay_get(db=db, user=current_user, path="/sell/inventory/v1/inventory_item", params={"limit": "200", "offset": "0"})
        if resp.status_code != 200: raise HTTPException(status_code=400, detail=resp.text)
        ebay_items = resp.json().get("inventoryItems", [])
        synced_count = 0
        for item in ebay_items:
            sku = item.get("sku")
            if not sku: continue
            listing = db.query(Listing).filter(Listing.owner_id == current_user.id, Listing.sku == sku).first()
            if not listing: continue
            lm = db.query(ListingMarketplace).filter(ListingMarketplace.listing_id == listing.id, ListingMarketplace.marketplace == "ebay").first()
            if not lm:
                lm = ListingMarketplace(listing_id=listing.id, marketplace="ebay")
                db.add(lm)
            if lm.status != "published": lm.status = "offer_created"
            synced_count += 1
        db.commit()
        return {"message": "Sync completed", "ebay_items_found": len(ebay_items), "local_listings_matched": synced_count}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")

@router.post("/ebay/{listing_id}/publish")
async def publish_to_ebay(listing_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    listing = _get_owned_listing_or_404(listing_id, current_user, db)
    raw_sku = listing.sku if (listing.sku and listing.sku.strip()) else f"USER{current_user.id}-LISTING{listing.id}"
    sku = _sanitize_sku(raw_sku.strip())
    if listing.sku != sku:
        listing.sku = sku
        db.add(listing)
        db.commit()
        db.refresh(listing)

    title = listing.title or "Untitled"
    description = listing.description or "No description"
    price = float(listing.price or 0)
    quantity = 1
    ebay_category_id = "11450"
    
    ebay_condition = "NEW"
    if listing.condition:
        c = listing.condition.lower()
        if "new" in c: ebay_condition = "NEW"
        elif "like" in c: ebay_condition = "LIKE_NEW"
        elif "good" in c or "used" in c: ebay_condition = "USED_GOOD"
        elif "parts" in c: ebay_condition = "FOR_PARTS_OR_NOT_WORKING"

    image_urls = []
    listing_images = db.query(ListingImage).filter(ListingImage.listing_id == listing_id).order_by(ListingImage.sort_order.asc()).all()
    base_url = str(request.base_url).rstrip('/')
    for img in listing_images:
        full_url = f"{base_url}{settings.media_url}/{img.file_path}"
        if full_url.startswith("http") and "127.0.0.1" not in full_url and "localhost" not in full_url:
            image_urls.append(full_url)
    if not image_urls:
        raw_images = getattr(listing, "image_urls", []) or []
        if isinstance(raw_images, list):
            for img in raw_images:
                if isinstance(img, str) and img.startswith("http") and "127.0.0.1" not in img and "localhost" not in img:
                    image_urls.append(img)

    merchant_location_key = await _ensure_merchant_location(db, current_user)
    policies = await _get_ebay_policies(db, current_user)
    if not policies: raise HTTPException(status_code=400, detail={"message": "eBay business policies not configured", "error": "MISSING_POLICIES"})

    inventory_payload = {
        "sku": sku, "locale": "en_US", "product": {"title": title, "description": description},
        "condition": ebay_condition, "availability": {"shipToLocationAvailability": {"quantity": quantity}}
    }
    if image_urls: inventory_payload["product"]["imageUrls"] = image_urls[:12]

    try:
        inv_resp = await ebay_put(db=db, user=current_user, path=f"/sell/inventory/v1/inventory_item/{quote(sku)}", json=inventory_payload)
    except EbayAuthError as e: raise HTTPException(status_code=400, detail=str(e))
    if inv_resp.status_code not in (200, 201, 204): raise HTTPException(status_code=400, detail={"message": "Failed to create Inventory Item", "ebay_resp": inv_resp.text})

    offer_payload = {
        "sku": sku, "marketplaceId": "EBAY_US", "format": "FIXED_PRICE", "availableQuantity": quantity,
        "categoryId": str(ebay_category_id), "listingDescription": description, "merchantLocationKey": merchant_location_key,
        "itemLocation": {"country": "US", "postalCode": "95112"},
        "listingPolicies": policies, "listingDuration": "GTC", "pricingSummary": {"price": {"currency": "USD", "value": f"{price:.2f}"}}
    }

    offer_resp = await ebay_post(db=db, user=current_user, path="/sell/inventory/v1/offer", json=offer_payload)
    offer_id = None
    if offer_resp.status_code in (200, 201): offer_id = offer_resp.json().get("offerId")
    else:
        try:
            body = offer_resp.json()
            for err in body.get("errors", []):
                if "offer entity already exists" in (err.get("message") or "").lower():
                    if err.get("parameters"): offer_id = err["parameters"][0]["value"]
                    break
        except: pass
        if offer_id:
            await ebay_put(db=db, user=current_user, path=f"/sell/inventory/v1/offer/{offer_id}", json=offer_payload)
        else: raise HTTPException(status_code=400, detail={"message": "Offer creation failed", "ebay_resp": offer_resp.text})

    publish_resp = await ebay_post(db=db, user=current_user, path=f"/sell/inventory/v1/offer/{offer_id}/publish", json={})
    ebay_listing_id = None
    if publish_resp.status_code in (200, 201): ebay_listing_id = publish_resp.json().get("listingId")
    else: raise HTTPException(status_code=400, detail={"message": "Publish failed", "ebay_resp": publish_resp.text})

    lm = db.query(ListingMarketplace).filter(ListingMarketplace.listing_id == listing.id, ListingMarketplace.marketplace == "ebay").first()
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
    return {"message": "Processed", "listing_id": ebay_listing_id, "url": lm.external_url}

@router.post("/ebay/{listing_id}/prepare-offer")
async def create_inventory_and_offer(listing_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    listing = _get_owned_listing_or_404(listing_id, current_user, db)
    raw_sku = listing.sku if (listing.sku and listing.sku.strip()) else f"USER{current_user.id}-LISTING{listing.id}"
    sku = _sanitize_sku(raw_sku.strip())
    if listing.sku != sku:
        listing.sku = sku
        db.add(listing)
        db.commit()
        db.refresh(listing)

    title = listing.title or "Untitled"
    description = listing.description or "No description"
    price = float(listing.price or 0)
    quantity = 1
    
    image_urls = []
    listing_images = db.query(ListingImage).filter(ListingImage.listing_id == listing_id).order_by(ListingImage.sort_order.asc()).all()
    base_url = str(request.base_url).rstrip('/')
    for img in listing_images:
        full_url = f"{base_url}{settings.media_url}/{img.file_path}"
        if full_url.startswith("http") and "127.0.0.1" not in full_url and "localhost" not in full_url: image_urls.append(full_url)
    if not image_urls:
        raw_images = getattr(listing, "image_urls", []) or []
        if isinstance(raw_images, list):
            for img in raw_images:
                if isinstance(img, str) and img.startswith("http") and "127.0.0.1" not in img and "localhost" not in img: image_urls.append(img)

    merchant_location_key = await _ensure_merchant_location(db, current_user)
    policies = await _get_ebay_policies(db, current_user)
    if not policies: raise HTTPException(status_code=400, detail={"message": "eBay business policies not configured", "error": "MISSING_POLICIES"})

    inventory_payload = {
        "sku": sku, "locale": "en_US", "product": {"title": title, "description": description},
        "condition": "NEW", "availability": {"shipToLocationAvailability": {"quantity": quantity}}
    }
    if image_urls: inventory_payload["product"]["imageUrls"] = image_urls[:12]

    try:
        inv_resp = await ebay_put(db=db, user=current_user, path=f"/sell/inventory/v1/inventory_item/{quote(sku)}", json=inventory_payload)
    except EbayAuthError as e: raise HTTPException(status_code=400, detail=str(e))
    if inv_resp.status_code not in (200, 201, 204): raise HTTPException(status_code=400, detail={"message": "Failed to create Inventory Item", "ebay_resp": inv_resp.text})

    offer_payload = {
        "sku": sku, "marketplaceId": "EBAY_US", "format": "FIXED_PRICE", "availableQuantity": quantity,
        "categoryId": "11450", "listingDescription": description, "merchantLocationKey": merchant_location_key,
        "itemLocation": {"country": "US", "postalCode": "95112"},
        "listingPolicies": policies, "listingDuration": "GTC", "pricingSummary": {"price": {"currency": "USD", "value": f"{price:.2f}"}}
    }

    offer_resp = await ebay_post(db=db, user=current_user, path="/sell/inventory/v1/offer", json=offer_payload)
    offer_id = None
    if offer_resp.status_code in (200, 201): offer_id = offer_resp.json().get("offerId")
    else:
        try:
            body = offer_resp.json()
            for err in body.get("errors", []):
                if "offer entity already exists" in (err.get("message") or "").lower():
                    if err.get("parameters"): offer_id = err["parameters"][0]["value"]
                    break
        except: pass
        if offer_id:
            await ebay_put(db=db, user=current_user, path=f"/sell/inventory/v1/offer/{offer_id}", json=offer_payload)
        else: raise HTTPException(status_code=400, detail={"message": "Offer creation failed", "ebay_resp": offer_resp.text})

    lm = db.query(ListingMarketplace).filter(ListingMarketplace.listing_id == listing.id, ListingMarketplace.marketplace == "ebay").first()
    if not lm:
        lm = ListingMarketplace(listing_id=listing.id, marketplace="ebay")
        db.add(lm)
    lm.status = "offer_created"
    lm.sku = sku
    lm.offer_id = offer_id
    db.commit()
    return {"message": "Inventory and offer prepared (not published)", "offer_id": offer_id, "sku": sku}

@router.get("/ebay/connect")
def ebay_connect(current_user: User = Depends(get_current_user)):
    params = {"client_id": settings.ebay_client_id, "redirect_uri": settings.ebay_redirect_uri, "response_type": "code", "scope": " ".join(EBAY_SCOPES), "state": str(current_user.id)}
    base = "https://auth.sandbox.ebay.com/oauth2/authorize" if settings.ebay_environment == "sandbox" else "https://auth.ebay.com/oauth2/authorize"
    return {"auth_url": f"{base}?{urlencode(params)}"}

@router.get("/ebay/oauth/callback")
async def ebay_oauth_callback(request: Request, db: Session = Depends(get_db)):
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state: raise HTTPException(status_code=400, detail="Missing code/state")
    try: user = db.query(User).filter(User.id == int(state)).first()
    except: raise HTTPException(status_code=400, detail="Invalid state")
    if not user: raise HTTPException(status_code=404, detail="User not found")

    token_url = "https://api.sandbox.ebay.com/identity/v1/oauth2/token" if settings.ebay_environment == "sandbox" else "https://api.ebay.com/identity/v1/oauth2/token"
    raw = f"{settings.ebay_client_id}:{settings.ebay_client_secret}"
    basic = base64.b64encode(raw.encode("utf-8")).decode("utf-8")
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data={"grant_type": "authorization_code", "code": code, "redirect_uri": settings.ebay_redirect_uri}, headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {basic}"})
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

@router.get("/poshmark/connect")
def poshmark_connect(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Create a short-lived connect token and return a connect URL containing the token.
    The token is valid for a short window (10 minutes) and used by the system-browser flow.
    """
    base_url = str(request.base_url).rstrip('/')
    # create secure token
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=10)
    ct = ConnectToken(token=token, user_id=current_user.id, expires_at=expires_at)
    db.add(ct)
    db.commit()
    return {"connect_url": f"{base_url}/marketplaces/poshmark/connect/form?token={token}"}

@router.get("/poshmark/connect/form")
def poshmark_connect_form(request: Request, token: str, db: Session = Depends(get_db)):
    # Validate token and map to user
    try:
        token_row = db.query(ConnectToken).filter(ConnectToken.token == token, ConnectToken.expires_at > datetime.utcnow()).first()
    except Exception:
        return HTMLResponse(content="Invalid request", status_code=400)
    if not token_row:
        return HTMLResponse(content="Invalid or expired token", status_code=400)
    user = db.query(User).filter(User.id == token_row.user_id).first()
    if not user:
        return HTMLResponse(content="User not found", status_code=404)
    # Serve a small form that lets a user paste cookies (from document.cookie)
    # and submit them back to the server. This allows a fast "system browser"
    # flow where the browser posts cookies back to the app without running Playwright.
    base_url = str(request.base_url).rstrip('/')
    submit_url = f"{base_url}/marketplaces/poshmark/connect/cookies_form"
    return HTMLResponse(content="""
<html>
    <head>
        <meta charset="utf-8" />
        <title>Poshmark Connect</title>
        <style>body{{font-family: Arial, sans-serif;max-width:900px;margin:28px;}}textarea{{width:100%;height:140px}}code{{background:#f3f3f3;padding:2px 4px;border-radius:3px}}</style>
    </head>
    <body>
        <h2>Poshmark Connect — One-Click Helper</h2>
        <p>Best flow: sign in to <b>poshmark.com</b> in your browser, then run the small bookmarklet below while on <b>poshmark.com</b>. The bookmarklet will copy your session cookies and open this connect page, which will receive the cookies automatically.</p>

        <h3>1) Drag this link to your bookmarks bar (one-time)</h3>
        <p>
            <a id="bmLink" href="#">Copy Poshmark Cookies &amp; Open Connect</a>
        </p>

        <h3>2) Or copy this Bookmarklet JS manually</h3>
        <p>Open your bookmarks manager and create a new bookmark with the following URL as its address:</p>
        <textarea id="bmCode" readonly></textarea>

        <hr/>
        <h3>3) When ready, paste or receive cookies below</h3>
        <form id="cookieForm" method="post" action="{submit_url}">
            <input type="hidden" name="token" value="{token}" />
            <label for="cookieString">Cookie string (or JSON array):</label>
            <textarea id="cookieString" name="cookie_string" placeholder="sessionid=...; un=...; ..."></textarea>
            <div style="margin-top:12px">
                <label><input type="checkbox" id="autoSubmit" /> Auto-submit when cookies received</label>
                <div style="margin-top:8px"><button type="submit">Submit Cookies</button></div>
            </div>
        </form>

        <hr/>
        <h4>Notes</h4>
        <ul>
            <li>The bookmarklet must be executed while you are on a poshmark.com page (after signing in).</li>
            <li>When executed, it will open this connect page and send your cookies here securely via <code>postMessage</code>.</li>
            <li>We recommend deleting the bookmarklet after use if you are on a shared machine.</li>
        </ul>

        <script>
            // Build the bookmarklet code (user can copy or drag the link)
            (function(){
                const connectUrl = '{submit_url}';
                const bm = "javascript:(function(){var url='"+connectUrl+"';var w=window.open(url,'_blank');var cookies=document.cookie;var i=setInterval(function(){try{w.postMessage({{type:'poshmark_cookies',cookies:cookies}},'*')}catch(e){}},300);setTimeout(function(){clearInterval(i)},15000);})();";
                const bmCodeEl = document.getElementById('bmCode');
                const bmLink = document.getElementById('bmLink');
                bmCodeEl.value = bm;
                bmLink.setAttribute('href', bm);
                bmLink.setAttribute('title', 'Drag this to your bookmarks bar or click while on poshmark.com');
            })();

            // Listen for cookie messages from bookmarklet (postMessage)
            window.addEventListener('message', function(ev) {
                try {
                    const data = ev.data || {};
                    if (data.type && data.type === 'poshmark_cookies' && data.cookies) {
                        const textarea = document.getElementById('cookieString');
                        textarea.value = data.cookies;
                        // Optionally auto-submit
                        const auto = document.getElementById('autoSubmit');
                        if (auto && auto.checked) {
                            document.getElementById('cookieForm').submit();
                        }
                    }
                } catch (e) {
                    // ignore
                }
            }, false);
        </script>
    </body>
</html>
""".replace("{submit_url}", submit_url).replace("{token}", token))


@router.post("/poshmark/connect/cookies_form")
def connect_poshmark_cookies_form(
    token: str = Form(...),
    cookie_string: str = Form(...),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    # Validate and consume token
    try:
        token_row = db.query(ConnectToken).filter(ConnectToken.token == token, ConnectToken.expires_at > datetime.utcnow()).first()
    except Exception:
        return HTMLResponse(content="Invalid token", status_code=400)
    if not token_row:
        return HTMLResponse(content="Invalid or expired token", status_code=400)

    user = db.query(User).filter(User.id == token_row.user_id).first()
    if not user:
        return HTMLResponse(content="User not found", status_code=404)

    # consume the token so it cannot be reused
    try:
        db.delete(token_row)
        db.commit()
    except Exception:
        db.rollback()

    # Try JSON first, then fallback to name=value;name2=value2 parsing
    cookies = []
    cookie_string = (cookie_string or "").strip()
    try:
        if cookie_string.startswith('['):
            cookies = json.loads(cookie_string)
        elif cookie_string.startswith('{'):
            # single object -> convert to array
            obj = json.loads(cookie_string)
            if isinstance(obj, dict):
                cookies = [obj]
        else:
            # parse document.cookie like string: k1=v1; k2=v2
            parts = cookie_string.split(';')
            for p in parts:
                p = p.strip()
                if not p:
                    continue
                if '=' in p:
                    name, value = p.split('=', 1)
                    cookies.append({"name": name.strip(), "value": value.strip()})
    except Exception as e:
        return HTMLResponse(content=f"Failed to parse cookies: {e}", status_code=400)

    # Save to DB (reuse logic similar to cookie-based API)
    try:
        username = "Connected Account"
        try:
            for c in cookies:
                if c.get('name') == 'un' or c.get('name') == 'username':
                    username = c.get('value')
                    break
        except Exception:
            pass

        cookies_json = json.dumps(cookies)

        account = db.query(MarketplaceAccount).filter(
            MarketplaceAccount.user_id == user.id,
            MarketplaceAccount.marketplace == "poshmark"
        ).first()

        if account:
            account.username = username
            account.access_token = cookies_json
        else:
            new_account = MarketplaceAccount(
                user_id=user.id,
                marketplace="poshmark",
                username=username,
                access_token=cookies_json,
            )
            db.add(new_account)

        db.commit()

        # Schedule background verification (non-blocking)
        try:
            if background_tasks is not None:
                async def _verify(cookie_json: str, uid: int):
                    logger = logging.getLogger("resalehub.poshmark")
                    try:
                        cookies = json.loads(cookie_json)
                        cookie_header = "; ".join([f"{c.get('name')}={c.get('value')}" for c in cookies if c.get('name')])
                        res = await verify_poshmark_cookie(cookie_header)
                        logger.info("poshmark: cookie verification succeeded for user %s -> %s", uid, res)
                    except Exception as e:
                        logger.exception("poshmark: cookie verification failed for user %s: %s", uid, e)

                background_tasks.add_task(_verify, cookies_json, user.id)
        except Exception:
            # verification is best-effort; don't fail the user's flow
            pass

        return HTMLResponse(content=f"<html><body><h3>Poshmark cookies saved for user {user.email}</h3><p>Verification queued. You may close this window.</p></body></html>")
    except Exception as e:
        db.rollback()
        traceback.print_exc()
        return HTMLResponse(content=f"Server error saving cookies: {e}", status_code=500)

# ---------------------------------------------------------
# [FIX] Poshmark Cookie-Based Connection (Fixed)
# ---------------------------------------------------------
@router.post("/poshmark/connect/cookies")
def connect_poshmark_cookies(
    # [FIX] Ensure Body import and type hints are present at top of file
    cookies: List[Dict[str, Any]] = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Connect Poshmark using cookies.
    Removed 'is_active' to fix TypeError.
    """
    print(f">>> [DEBUG] Received cookie connection request from {current_user.email}")
    
    try:
        # 1. Username extraction
        username = "Connected Account"
        try:
            for c in cookies:
                if c.get('name') == 'un' or c.get('name') == 'username':
                    username = c.get('value')
                    break
        except Exception as e:
            print(f">>> [WARNING] Failed to extract username from cookies: {e}")

        print(f">>> [DEBUG] Extracted Username: {username}")

        # 2. JSON Serialize
        cookies_json = json.dumps(cookies)

        # 3. Save to DB (Updated: Removed is_active=True)
        account = db.query(MarketplaceAccount).filter(
            MarketplaceAccount.user_id == current_user.id,
            MarketplaceAccount.marketplace == "poshmark"
        ).first()

        if account:
            print(f">>> [DEBUG] Updating existing account for {current_user.id}")
            account.username = username
            account.access_token = cookies_json
            # account.is_active = True  <-- [REMOVED]
        else:
            print(f">>> [DEBUG] Creating new account for {current_user.id}")
            new_account = MarketplaceAccount(
                user_id=current_user.id,
                marketplace="poshmark",
                username=username,
                access_token=cookies_json,
                # is_active=True <-- [REMOVED]
            )
            db.add(new_account)
        
        db.commit()
        if account: db.refresh(account)
        
        print(">>> [SUCCESS] Poshmark connected successfully via cookies.")
        return {"status": "connected", "username": username}

    except Exception as e:
        db.rollback()
        print(f">>> [CRITICAL ERROR] Failed to save Poshmark cookies: {str(e)}")
        traceback.print_exc()
        raise HTTPException(
            status_code=500, 
            detail=f"Server Error saving cookies: {str(e)}"
        )

@router.get("/poshmark/status")
def poshmark_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = db.query(MarketplaceAccount).filter(MarketplaceAccount.user_id == current_user.id, MarketplaceAccount.marketplace == "poshmark").first()
    connected = account is not None and account.access_token is not None
    return {"connected": connected, "marketplace": "poshmark", "username": account.username if account else None}

@router.delete("/poshmark/disconnect")
def poshmark_disconnect(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = db.query(MarketplaceAccount).filter(MarketplaceAccount.user_id == current_user.id, MarketplaceAccount.marketplace == "poshmark").first()
    if account:
        db.delete(account)
        db.commit()
    return {"message": "Poshmark account disconnected"}

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
async def publish_to_poshmark(listing_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    listing = _get_owned_listing_or_404(listing_id, current_user, db)
    listing_images = db.query(ListingImage).filter(ListingImage.listing_id == listing_id).order_by(ListingImage.sort_order.asc()).all()
    if not listing_images: raise HTTPException(status_code=400, detail="At least one image is required")
    base_url = str(request.base_url).rstrip('/')
    try:
        result = await poshmark_publish_listing(db=db, user=current_user, listing=listing, listing_images=listing_images, base_url=base_url, settings=settings)
        lm = db.query(ListingMarketplace).filter(ListingMarketplace.listing_id == listing.id, ListingMarketplace.marketplace == "poshmark").first()
        if not lm:
            lm = ListingMarketplace(listing_id=listing.id, marketplace="poshmark")
            db.add(lm)
        lm.status = result.get("status", "published")
        lm.external_item_id = result.get("external_item_id")
        lm.external_url = result.get("url")
        db.commit()
        return {"message": "Published to Poshmark", "url": result.get("url"), "listing_id": result.get("external_item_id")}
    except PoshmarkAuthError as e: raise HTTPException(status_code=401, detail=str(e))
    except PoshmarkPublishError as e: raise HTTPException(status_code=400, detail=str(e))
    except Exception as e: raise HTTPException(status_code=500, detail=f"Publish failed: {str(e)}")

@router.get("/ebay/me")
async def ebay_me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try: resp = await ebay_get(db=db, user=current_user, path="/sell/account/v1/fulfillment_policy", params={"marketplace_id": "EBAY_US"})
    except EbayAuthError as e: raise HTTPException(status_code=400, detail=str(e))
    return resp.json()

@router.get("/poshmark/inventory")
async def poshmark_inventory(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.services.poshmark_client import get_poshmark_inventory
    try:
        items = await get_poshmark_inventory(db, current_user)
        return {"items": items, "total": len(items)}
    except PoshmarkAuthError as e: raise HTTPException(status_code=401, detail=str(e))
    except Exception as e: raise HTTPException(status_code=500, detail=f"Failed to fetch Poshmark inventory: {str(e)}")