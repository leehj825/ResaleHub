from datetime import datetime, timedelta
import random
import string
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_user,
)
from app.models.user import User
from app.models.pairing_code import PairingCode
from app.models.marketplace_account import MarketplaceAccount
from app.schemas.user import UserCreate, UserLogin, UserRead, Token

router = APIRouter(prefix="/auth", tags=["auth"])
api_router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


@router.post("/signup", response_model=UserRead)
def signup(user_in: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == user_in.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(user_in: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == user_in.email).first()
    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires,
    )
    return Token(access_token=access_token)


@router.get("/me", response_model=UserRead)
def read_me(current_user: User = Depends(get_current_user)):
    return current_user


# ============================================================================
# Desktop-to-Cloud Pairing Code Flow
# ============================================================================

def generate_pairing_code() -> str:
    """Generate a random 6-digit pairing code."""
    return ''.join(random.choices(string.digits, k=6))


@api_router.post("/pairing-code")
def create_pairing_code(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generate a new 6-digit pairing code for the authenticated user.
    The code expires in 10 minutes.
    """
    # Clean up expired codes for this user
    db.query(PairingCode).filter(
        PairingCode.user_id == current_user.id,
        PairingCode.expires_at < datetime.utcnow()
    ).delete()
    
    # Generate unique code (retry if collision)
    max_attempts = 10
    for _ in range(max_attempts):
        code = generate_pairing_code()
        existing = db.query(PairingCode).filter(PairingCode.code == code).first()
        if not existing:
            break
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to generate unique pairing code"
        )
    
    # Create pairing code (expires in 10 minutes)
    pairing_code = PairingCode(
        code=code,
        user_id=current_user.id,
        expires_at=datetime.utcnow() + timedelta(minutes=10),
        is_used=False,
        cookies_received=False,
    )
    db.add(pairing_code)
    db.commit()
    db.refresh(pairing_code)
    
    return {
        "code": code,
        "expires_at": pairing_code.expires_at.isoformat(),
        "expires_in_seconds": 600,
    }


@api_router.post("/sync-extension")
def sync_extension(
    request: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
):
    """
    Receive cookies from Chrome extension along with pairing code.
    Finds the user associated with the code and saves the cookies.
    """
    pairing_code = request.get('pairing_code')
    cookies = request.get('cookies', [])
    username = request.get('username')  # Username sent by extension
    
    if not pairing_code or len(str(pairing_code)) != 6:
        raise HTTPException(
            status_code=400,
            detail="Invalid pairing code format"
        )
    
    if not cookies or len(cookies) == 0:
        raise HTTPException(
            status_code=400,
            detail="No cookies provided"
        )
    
    # Find pairing code
    pairing = db.query(PairingCode).filter(
        PairingCode.code == pairing_code,
        PairingCode.expires_at > datetime.utcnow(),
        PairingCode.is_used == False,
    ).first()
    
    if not pairing:
        raise HTTPException(
            status_code=404,
            detail="Invalid or expired pairing code"
        )
    
    # Mark as used
    pairing.is_used = True
    pairing.used_at = datetime.utcnow()
    pairing.cookies_received = True
    
    # Use username from extension if provided, otherwise try to extract from cookies
    if not username or username == "Connected Account":
        # Fallback: Extract username from cookies
        for cookie in cookies:
            if cookie.get('name') in ['un', 'username']:
                username = cookie.get('value', username)
                break
        
        # If still not found, use default
        if not username or username == "Connected Account":
            username = "Connected Account"
    
    # Save cookies to marketplace account
    import json
    cookies_json = json.dumps(cookies)
    
    account = db.query(MarketplaceAccount).filter(
        MarketplaceAccount.user_id == pairing.user_id,
        MarketplaceAccount.marketplace == "poshmark"
    ).first()
    
    if account:
        account.username = username
        account.access_token = cookies_json
    else:
        account = MarketplaceAccount(
            user_id=pairing.user_id,
            marketplace="poshmark",
            username=username,
            access_token=cookies_json,
        )
        db.add(account)
    
    db.commit()
    
    return {
        "status": "success",
        "message": "Cookies synced successfully",
        "username": username,
    }


@api_router.get("/pairing-status/{code}")
def get_pairing_status(
    code: str,
    db: Session = Depends(get_db),
):
    """
    Check the status of a pairing code.
    Returns whether cookies have been received.
    """
    if len(code) != 6:
        raise HTTPException(
            status_code=400,
            detail="Invalid pairing code format"
        )
    
    pairing = db.query(PairingCode).filter(PairingCode.code == code).first()
    
    if not pairing:
        return {
            "status": "not_found",
            "message": "Pairing code not found",
            "cookies_received": False,
        }
    
    if pairing.expires_at < datetime.utcnow():
        return {
            "status": "expired",
            "message": "Pairing code has expired",
            "cookies_received": False,
        }
    
    if pairing.cookies_received:
        return {
            "status": "success",
            "message": "Cookies received",
            "cookies_received": True,
            "used_at": pairing.used_at.isoformat() if pairing.used_at else None,
        }
    
    return {
        "status": "pending",
        "message": "Waiting for cookies",
        "cookies_received": False,
        "expires_at": pairing.expires_at.isoformat(),
    }
