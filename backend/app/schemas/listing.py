from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from pydantic import BaseModel, ConfigDict, Field


# --- [수정됨] 마켓 정보 스키마 (SKU, OfferID 추가) ---
class ListingMarketplaceSchema(BaseModel):
    marketplace: str
    external_url: Optional[str] = None
    status: str
    external_item_id: Optional[str] = None
    sku: Optional[str] = None       # [추가됨]
    offer_id: Optional[str] = None  # [추가됨]
    
    model_config = ConfigDict(from_attributes=True)


class ListingBase(BaseModel):
    title: str = Field(max_length=255)
    description: Optional[str] = None
    price: Decimal = Field(ge=0)
    currency: str = Field(default="USD", max_length=3)


class ListingCreate(ListingBase):
    pass


class ListingUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    price: Optional[Decimal] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, max_length=3)
    status: Optional[str] = None


class ListingRead(ListingBase):
    id: int
    status: str
    created_at: datetime
    updated_at: datetime
    thumbnail_url: Optional[str] = None
    
    # --- 마켓플레이스 연동 정보 ---
    marketplace_links: List[ListingMarketplaceSchema] = []

    model_config = ConfigDict(from_attributes=True)