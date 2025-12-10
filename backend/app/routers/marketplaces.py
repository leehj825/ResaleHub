from typing import List
from urllib.parse import urlencode, quote
import base64
import re
import json
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

from app.services.ebay_client import ebay_get, ebay_post, ebay_put, ebay_delete, EbayAuthError

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
    """
    Sanitize SKU to only contain alphanumeric characters, hyphens, underscores, and forward slashes.
    Replaces invalid characters with hyphens and removes consecutive hyphens.
    """
    # Replace any non-alphanumeric, non-hyphen, non-underscore, non-forward-slash characters with hyphens
    sanitized = re.sub(r'[^a-zA-Z0-9_/-]', '-', raw_sku)
    # Remove consecutive hyphens (but preserve forward slashes)
    sanitized = re.sub(r'-+', '-', sanitized)
    # Remove leading/trailing hyphens and underscores (but preserve forward slashes)
    sanitized = sanitized.strip('-').strip('_')
    # Ensure it's not empty
    if not sanitized:
        sanitized = "SKU"
    return sanitized

# ---------------------------------------------------------
# [FIX] Helper: Check and Opt-In to Business Policies
# ---------------------------------------------------------
async def _ensure_business_policies_opted_in(db: Session, user: User) -> bool:
    """
    Checks if account is opted into Business Policies and opts in if not.
    Returns True if opted in (or successfully opted in), False otherwise.
    """
    try:
        # Check current opt-in status
        programs_resp = await ebay_get(
            db=db,
            user=user,
            path="/sell/account/v1/program/get_opted_in_programs"
        )
        
        if programs_resp.status_code == 200:
            programs_data = programs_resp.json()
            programs = programs_data.get("programs", [])
            
            # Check if already opted into Business Policies
            for program in programs:
                if program.get("programType") == "SELLING_POLICY_MANAGEMENT":
                    print(">>> Account is already opted into Business Policies")
                    return True
            
            # Not opted in, try to opt in
            print(">>> Account not opted into Business Policies. Attempting to opt in...")
            opt_in_resp = await ebay_post(
                db=db,
                user=user,
                path="/sell/account/v1/program/opt_in",
                json={"programType": "SELLING_POLICY_MANAGEMENT"}
            )
            
            if opt_in_resp.status_code in (200, 201, 204):
                print(">>> Successfully opted into Business Policies")
                return True
            else:
                try:
                    error_body = opt_in_resp.json()
                    error_str = json.dumps(error_body, indent=2)
                    print(f">>> Failed to opt into Business Policies (Status: {opt_in_resp.status_code})")
                    print(f">>> Response: {error_str}")
                except:
                    print(f">>> Failed to opt into Business Policies (Status: {opt_in_resp.status_code}): {opt_in_resp.text}")
                return False
        else:
            print(f">>> Failed to check opt-in status (Status: {programs_resp.status_code})")
            return False
            
    except Exception as e:
        print(f">>> Error checking/opting into Business Policies: {e}")
        return False

# ---------------------------------------------------------
# [FIX] Helper: Create Default eBay Business Policies
# ---------------------------------------------------------
async def _create_default_policies(db: Session, user: User):
    """
    Creates default payment, return, and fulfillment policies if they don't exist.
    Returns a dict with policy IDs.
    """
    policies_created = {}
    
    try:
        # Create Fulfillment Policy
        fulfillment_payload = {
            "name": "Standard Shipping",
            "marketplaceId": "EBAY_US",
            "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
            "handlingTime": {
                "value": 1,
                "unit": "DAY"  # eBay expects DAY here
            },
            "shippingOptions": [
                {
                    "optionType": "DOMESTIC",  # Required field
                    "costType": "FLAT_RATE",
                    "shippingServices": [
                        {
                            "shippingCarrierCode": "USPS",
                            # Use a widely-accepted domestic service for sandbox
                            "shippingServiceCode": "USPSGroundAdvantage",
                            "freeShipping": False
                        }
                    ]
                }
            ]
        }
        
        fulfillment_resp = await ebay_post(
            db=db,
            user=user,
            path="/sell/account/v1/fulfillment_policy",
            json=fulfillment_payload
        )
        
        if fulfillment_resp.status_code in (200, 201):
            policies_created["fulfillmentPolicyId"] = fulfillment_resp.json().get("fulfillmentPolicyId")
            print(f">>> Created fulfillment policy: {policies_created['fulfillmentPolicyId']}")
        else:
            # Check if policy already exists or get error details
            try:
                error_body = fulfillment_resp.json()
                error_str = json.dumps(error_body, indent=2)
                print(f">>> Fulfillment policy creation failed (Status: {fulfillment_resp.status_code})")
                print(f">>> Response: {error_str}")
                
                if "already exists" in str(error_body).lower() or "duplicate" in str(error_body).lower():
                    try:
                        existing = await ebay_get(db=db, user=user, path="/sell/account/v1/fulfillment_policy", params={"marketplace_id": "EBAY_US"})
                        if existing.status_code == 200:
                            existing_policies = existing.json().get("fulfillmentPolicies", [])
                            if existing_policies:
                                policies_created["fulfillmentPolicyId"] = existing_policies[0].get("fulfillmentPolicyId")
                                print(f">>> Using existing fulfillment policy: {policies_created['fulfillmentPolicyId']}")
                    except Exception as e:
                        print(f">>> Error reading existing fulfillment policies: {e}")
            except Exception as e:
                print(f">>> Error processing fulfillment policy response: {e}")
            # Fallback: if creation failed for any reason, try to reuse first existing policy
            if "fulfillmentPolicyId" not in policies_created:
                try:
                    existing = await ebay_get(db=db, user=user, path="/sell/account/v1/fulfillment_policy", params={"marketplace_id": "EBAY_US"})
                    if existing.status_code == 200:
                        existing_policies = existing.json().get("fulfillmentPolicies", [])
                        if existing_policies:
                            policies_created["fulfillmentPolicyId"] = existing_policies[0].get("fulfillmentPolicyId")
                            print(f">>> Using fallback fulfillment policy: {policies_created['fulfillmentPolicyId']}")
                except Exception as e:
                    print(f">>> Error during fulfillment policy fallback: {e}")
        
        # Create Payment Policy
        payment_payload = {
            "name": "Standard Payment",
            "marketplaceId": "EBAY_US",
            "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
            # Managed payments: do not specify paymentMethods
            "immediatePay": False
        }
        
        payment_resp = await ebay_post(
            db=db,
            user=user,
            path="/sell/account/v1/payment_policy",
            json=payment_payload
        )
        
        if payment_resp.status_code in (200, 201):
            policies_created["paymentPolicyId"] = payment_resp.json().get("paymentPolicyId")
            print(f">>> Created payment policy: {policies_created['paymentPolicyId']}")
        else:
            try:
                error_body = payment_resp.json()
                error_str = json.dumps(error_body, indent=2)
                print(f">>> Payment policy creation failed (Status: {payment_resp.status_code})")
                print(f">>> Response: {error_str}")
                
                if "already exists" in str(error_body).lower() or "duplicate" in str(error_body).lower():
                    try:
                        existing = await ebay_get(db=db, user=user, path="/sell/account/v1/payment_policy", params={"marketplace_id": "EBAY_US"})
                        if existing.status_code == 200:
                            existing_policies = existing.json().get("paymentPolicies", [])
                            if existing_policies:
                                policies_created["paymentPolicyId"] = existing_policies[0].get("paymentPolicyId")
                                print(f">>> Using existing payment policy: {policies_created['paymentPolicyId']}")
                    except Exception as e:
                        print(f">>> Error reading existing payment policies: {e}")
            except Exception as e:
                print(f">>> Error processing payment policy response: {e}")
            if "paymentPolicyId" not in policies_created:
                try:
                    existing = await ebay_get(db=db, user=user, path="/sell/account/v1/payment_policy", params={"marketplace_id": "EBAY_US"})
                    if existing.status_code == 200:
                        existing_policies = existing.json().get("paymentPolicies", [])
                        if existing_policies:
                            policies_created["paymentPolicyId"] = existing_policies[0].get("paymentPolicyId")
                            print(f">>> Using fallback payment policy: {policies_created['paymentPolicyId']}")
                except Exception as e:
                    print(f">>> Error during payment policy fallback: {e}")
        
        # Create Return Policy
        return_payload = {
            "name": "30-Day Returns",
            "marketplaceId": "EBAY_US",
            "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
            "returnsAccepted": True,
            "returnPeriod": {
                "value": 30,
                "unit": "DAY"
            },
            "refundMethod": "MONEY_BACK",
            "returnShippingCostPayer": "BUYER"
        }
        
        return_resp = await ebay_post(
            db=db,
            user=user,
            path="/sell/account/v1/return_policy",
            json=return_payload
        )
        
        if return_resp.status_code in (200, 201):
            policies_created["returnPolicyId"] = return_resp.json().get("returnPolicyId")
            print(f">>> Created return policy: {policies_created['returnPolicyId']}")
        else:
            try:
                error_body = return_resp.json()
                error_str = json.dumps(error_body, indent=2)
                print(f">>> Return policy creation failed (Status: {return_resp.status_code})")
                print(f">>> Response: {error_str}")
                
                if "already exists" in str(error_body).lower() or "duplicate" in str(error_body).lower():
                    try:
                        existing = await ebay_get(db=db, user=user, path="/sell/account/v1/return_policy", params={"marketplace_id": "EBAY_US"})
                        if existing.status_code == 200:
                            existing_policies = existing.json().get("returnPolicies", [])
                            if existing_policies:
                                policies_created["returnPolicyId"] = existing_policies[0].get("returnPolicyId")
                                print(f">>> Using existing return policy: {policies_created['returnPolicyId']}")
                    except Exception as e:
                        print(f">>> Error reading existing return policies: {e}")
            except Exception as e:
                print(f">>> Error processing return policy response: {e}")
        
        # Final fallback: fill any missing policy IDs from existing lists
        try:
            if "fulfillmentPolicyId" not in policies_created:
                existing = await ebay_get(db=db, user=user, path="/sell/account/v1/fulfillment_policy", params={"marketplace_id": "EBAY_US"})
                if existing.status_code == 200:
                    existing_policies = existing.json().get("fulfillmentPolicies", [])
                    if existing_policies:
                        policies_created["fulfillmentPolicyId"] = existing_policies[0].get("fulfillmentPolicyId")
                        print(f">>> Using final fallback fulfillment policy: {policies_created['fulfillmentPolicyId']}")
            if "paymentPolicyId" not in policies_created:
                existing = await ebay_get(db=db, user=user, path="/sell/account/v1/payment_policy", params={"marketplace_id": "EBAY_US"})
                if existing.status_code == 200:
                    existing_policies = existing.json().get("paymentPolicies", [])
                    if existing_policies:
                        policies_created["paymentPolicyId"] = existing_policies[0].get("paymentPolicyId")
                        print(f">>> Using final fallback payment policy: {policies_created['paymentPolicyId']}")
            if "returnPolicyId" not in policies_created:
                existing = await ebay_get(db=db, user=user, path="/sell/account/v1/return_policy", params={"marketplace_id": "EBAY_US"})
                if existing.status_code == 200:
                    existing_policies = existing.json().get("returnPolicies", [])
                    if existing_policies:
                        policies_created["returnPolicyId"] = existing_policies[0].get("returnPolicyId")
                        print(f">>> Using final fallback return policy: {policies_created['returnPolicyId']}")
        except Exception as e:
            print(f">>> Error during final fallback fetch: {e}")

        if len(policies_created) == 3:
            return policies_created
        else:
            print(f">>> Warning: Only created {len(policies_created)}/3 policies")
            return None
            
    except Exception as e:
        print(f">>> Error creating default policies: {e}")
        return None

# ---------------------------------------------------------
# [FIX] Helper: Get eBay Business Policies
# ---------------------------------------------------------
async def _get_ebay_policies(db: Session, user: User):
    """
    Fetches payment, return, and fulfillment policy IDs from eBay Account API.
    Returns a dict with policy IDs or None if policies are not set up.
    """
    try:
        # Get fulfillment policies
        fulfillment_resp = await ebay_get(
            db=db,
            user=user,
            path="/sell/account/v1/fulfillment_policy",
            params={"marketplace_id": "EBAY_US"}
        )
        
        # Get payment policies
        payment_resp = await ebay_get(
            db=db,
            user=user,
            path="/sell/account/v1/payment_policy",
            params={"marketplace_id": "EBAY_US"}
        )
        
        # Get return policies
        return_resp = await ebay_get(
            db=db,
            user=user,
            path="/sell/account/v1/return_policy",
            params={"marketplace_id": "EBAY_US"}
        )
        
        fulfillment_policies = fulfillment_resp.json().get("fulfillmentPolicies", []) if fulfillment_resp.status_code == 200 else []
        payment_policies = payment_resp.json().get("paymentPolicies", []) if payment_resp.status_code == 200 else []
        return_policies = return_resp.json().get("returnPolicies", []) if return_resp.status_code == 200 else []
        
        # Helper to get policy ID (prefer "default" or "standard" named policies, otherwise first)
        def get_policy_id(policies, policy_id_key="fulfillmentPolicyId"):
            if not policies:
                return None
            # First try to find "default" or "standard" named policy
            for policy in policies:
                name = policy.get("name", "").lower()
                if "default" in name or "standard" in name:
                    return policy.get(policy_id_key)
            # Otherwise return first policy
            return policies[0].get(policy_id_key) if policies else None
        
        fulfillment_policy_id = get_policy_id(fulfillment_policies, "fulfillmentPolicyId")
        payment_policy_id = get_policy_id(payment_policies, "paymentPolicyId")
        return_policy_id = get_policy_id(return_policies, "returnPolicyId")
        
        if fulfillment_policy_id and payment_policy_id and return_policy_id:
            return {
                "fulfillmentPolicyId": fulfillment_policy_id,
                "paymentPolicyId": payment_policy_id,
                "returnPolicyId": return_policy_id
            }
        else:
            print(f">>> Warning: Missing policies - Fulfillment: {fulfillment_policy_id}, Payment: {payment_policy_id}, Return: {return_policy_id}")
            # Ensure account is opted into Business Policies first
            opted_in = await _ensure_business_policies_opted_in(db, user)
            if not opted_in:
                print(">>> Cannot create policies: Account not opted into Business Policies")
                return None
            
            # Try to create default policies
            print(f">>> Attempting to create default policies...")
            created_policies = await _create_default_policies(db, user)
            if created_policies:
                return created_policies
            return None
            
    except Exception as e:
        print(f">>> Warning: Failed to fetch eBay policies: {e}")
        return None

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


@router.delete("/ebay/inventory/{sku}")
async def delete_ebay_inventory_item(
    sku: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Deletes an inventory item in eBay by SKU.
    """
    encoded_sku = quote(sku)

    try:
        resp = await ebay_delete(
            db=db,
            user=current_user,
            path=f"/sell/inventory/v1/inventory_item/{encoded_sku}",
        )
    except EbayAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if resp.status_code not in (200, 204):
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        raise HTTPException(
            status_code=resp.status_code,
            detail={"message": "Failed to delete inventory item", "ebay_resp": body},
        )

    return {"message": "Deleted", "sku": sku}

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
    # Use proper sanitization function to ensure only valid characters
    sku = _sanitize_sku(raw_sku.strip())
    print(f">>> Publishing SKU: {sku} (sanitized from: {raw_sku})")

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
    
    # 3.5. [FIX] Get eBay Business Policies (Required for publishing)
    policies = await _get_ebay_policies(db, current_user)
    if not policies:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "eBay business policies not configured",
                "error": "MISSING_POLICIES",
                "instructions": "The system attempted to opt into Business Policies and create default policies but failed. Please check the console logs for specific error details. Note: If you just opted into Business Policies, it may take up to 24 hours to process. Alternatively, you can manually create payment, return, and fulfillment policies in your eBay Seller Hub at https://www.ebay.com/sh/landing."
            }
        )
    print(f">>> Using Policies - Fulfillment: {policies['fulfillmentPolicyId']}, Payment: {policies['paymentPolicyId']}, Return: {policies['returnPolicyId']}")

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
        try:
            error_body = inv_resp.json()
            error_body_str = json.dumps(error_body, indent=2)
        except:
            error_body_str = inv_resp.text
        print(f">>> Inventory Creation Failed (Status: {inv_resp.status_code})")
        print(f">>> Full Response Body:\n{error_body_str}")
        raise HTTPException(
            status_code=400, 
            detail={"message": "Failed to create Inventory Item", "ebay_resp": error_body_str}
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
        "itemLocation": {
            "country": "US",  # ISO 3166-1 alpha-2 country code
            "postalCode": "95112"  # Valid postal code for Sandbox (San Jose, CA)
        },
        "listingPolicies": {
            "fulfillmentPolicyId": policies["fulfillmentPolicyId"],
            "paymentPolicyId": policies["paymentPolicyId"],
            "returnPolicyId": policies["returnPolicyId"]
        },
        "listingDuration": "GTC",  # Good 'Til Cancelled (required field)
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
            update_resp = await ebay_put(
                db=db,
                user=current_user,
                path=f"/sell/inventory/v1/offer/{offer_id}",
                json=offer_payload
            )
            if update_resp.status_code not in (200, 201, 204):
                try:
                    error_body = update_resp.json()
                    error_body_str = json.dumps(error_body, indent=2)
                except:
                    error_body_str = update_resp.text
                print(f">>> Offer Update Failed (Status: {update_resp.status_code})")
                print(f">>> Full Response Body:\n{error_body_str}")
                raise HTTPException(
                    status_code=400,
                    detail={"message": "Failed to update existing offer", "ebay_resp": error_body_str}
                )
        else:
            try:
                error_body = offer_resp.json()
                error_body_str = json.dumps(error_body, indent=2)
            except:
                error_body_str = offer_resp.text
            print(f">>> Offer Creation Failed (Status: {offer_resp.status_code})")
            print(f">>> Full Response Body:\n{error_body_str}")
            raise HTTPException(status_code=400, detail={"message": "Offer creation failed", "ebay_resp": error_body_str})

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
        try:
            error_body = publish_resp.json()
            error_body_str = json.dumps(error_body, indent=2)
        except:
            error_body_str = publish_resp.text
        print(f">>> Publish Failed (Status: {publish_resp.status_code})")
        print(f">>> Full Response Body:\n{error_body_str}")
        raise HTTPException(status_code=400, detail={"message": "Publish failed", "ebay_resp": error_body_str})

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


@router.post("/ebay/{listing_id}/prepare-offer")
async def create_inventory_and_offer(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Creates/updates Inventory Item and Offer, but does NOT publish.
    Useful for staging before going live.
    """
    listing = _get_owned_listing_or_404(listing_id, current_user, db)

    raw_sku = listing.sku if (listing.sku and listing.sku.strip()) else f"USER{current_user.id}-LISTING{listing.id}"
    sku = _sanitize_sku(raw_sku.strip())
    print(f">>> Preparing (no publish) SKU: {sku} (sanitized from: {raw_sku})")

    if listing.sku != sku:
        listing.sku = sku
        db.add(listing)
        db.commit()
        db.refresh(listing)

    title = getattr(listing, "title", "Untitled")
    description = getattr(listing, "description", "No description") or "No description"
    price = float(getattr(listing, "price", 0) or 0)
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
    raw_images = getattr(listing, "image_urls", []) or []
    if isinstance(raw_images, list):
        for img in raw_images:
            if isinstance(img, str) and img.startswith("http") and "127.0.0.1" not in img and "localhost" not in img:
                image_urls.append(img)

    merchant_location_key = await _ensure_merchant_location(db, current_user)

    policies = await _get_ebay_policies(db, current_user)
    if not policies:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "eBay business policies not configured",
                "error": "MISSING_POLICIES",
            }
        )
    print(f">>> Using Policies - Fulfillment: {policies['fulfillmentPolicyId']}, Payment: {policies['paymentPolicyId']}, Return: {policies['returnPolicyId']}")

    inventory_payload = {
        "sku": sku,
        "locale": "en_US",
        "product": {
            "title": title,
            "description": description,
            # "imageUrls": image_urls
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
        try:
            error_body = inv_resp.json()
            error_body_str = json.dumps(error_body, indent=2)
        except:
            error_body_str = inv_resp.text
        print(f">>> Inventory (prepare) Failed (Status: {inv_resp.status_code})")
        print(f">>> Full Response Body:\n{error_body_str}")
        raise HTTPException(
            status_code=400,
            detail={"message": "Failed to create Inventory Item", "ebay_resp": error_body_str}
        )

    offer_payload = {
        "sku": sku,
        "marketplaceId": "EBAY_US",
        "format": "FIXED_PRICE",
        "availableQuantity": quantity,
        "categoryId": str(ebay_category_id),
        "listingDescription": description,
        "merchantLocationKey": merchant_location_key,
        "itemLocation": {
            "country": "US",
            "postalCode": "95112"
        },
        "listingPolicies": {
            "fulfillmentPolicyId": policies["fulfillmentPolicyId"],
            "paymentPolicyId": policies["paymentPolicyId"],
            "returnPolicyId": policies["returnPolicyId"]
        },
        "listingDuration": "GTC",
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
        try:
            body = offer_resp.json()
            for err in body.get("errors", []):
                if "offer entity already exists" in (err.get("message") or "").lower():
                    if err.get("parameters"):
                        offer_id = err["parameters"][0]["value"]
                    break
        except:
            body = None

        if offer_id:
            print(f">>> Offer exists ({offer_id}). Updating (no publish)...")
            update_resp = await ebay_put(
                db=db,
                user=current_user,
                path=f"/sell/inventory/v1/offer/{offer_id}",
                json=offer_payload
            )
            if update_resp.status_code not in (200, 201, 204):
                try:
                    error_body = update_resp.json()
                    error_body_str = json.dumps(error_body, indent=2)
                except:
                    error_body_str = update_resp.text
                print(f">>> Offer Update Failed (Status: {update_resp.status_code})")
                print(f">>> Full Response Body:\n{error_body_str}")
                raise HTTPException(
                    status_code=400,
                    detail={"message": "Failed to update existing offer", "ebay_resp": error_body_str}
                )
        else:
            try:
                error_body = offer_resp.json()
                error_body_str = json.dumps(error_body, indent=2)
            except:
                error_body_str = offer_resp.text
            print(f">>> Offer Creation Failed (Status: {offer_resp.status_code})")
            print(f">>> Full Response Body:\n{error_body_str}")
            raise HTTPException(status_code=400, detail={"message": "Offer creation failed", "ebay_resp": error_body_str})

    lm = db.query(ListingMarketplace).filter(
        ListingMarketplace.listing_id == listing.id,
        ListingMarketplace.marketplace == "ebay"
    ).first()

    if not lm:
        lm = ListingMarketplace(listing_id=listing.id, marketplace="ebay")
        db.add(lm)

    lm.status = "offer_created"
    lm.sku = sku
    lm.offer_id = offer_id
    lm.external_item_id = None
    lm.external_url = None

    db.commit()
    db.refresh(lm)

    return {
        "message": "Inventory and offer prepared (not published)",
        "offer_id": offer_id,
        "sku": sku,
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