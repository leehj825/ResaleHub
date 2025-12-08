from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from pydantic import BaseModel, ConfigDict, Field


# --- [추가됨] Marketplace 정보 스키마 ---
class ListingMarketplaceSchema(BaseModel):
    marketplace: str
    external_url: Optional[str] = None
    status: str
    external_item_id: Optional[str] = None

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

    # --- [추가됨] 이 리스팅이 어디에 올라갔는지 정보 포함 ---
    # models/listing.py 의 marketplace_links 관계 이름과 일치해야 함
    marketplace_links: List[ListingMarketplaceSchema] = []

    model_config = ConfigDict(from_attributes=True)
