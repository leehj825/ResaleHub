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
    
    # [추가됨] SKU 및 상태 (Import 기능 지원 및 상세 표시용)
    sku: Optional[str] = None
    condition: Optional[str] = None


class ListingCreate(ListingBase):
    # [추가됨] Import 시 사용되는 임시 필드들 (DB 컬럼 아님, 로직용)
    import_from_marketplace: Optional[str] = None  # 예: "ebay"
    import_external_id: Optional[str] = None       # eBay Item ID
    import_url: Optional[str] = None               # eBay Link


class ListingUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    price: Optional[Decimal] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, max_length=3)
    status: Optional[str] = None
    
    # [추가됨] 업데이트 가능하도록 추가
    sku: Optional[str] = None
    condition: Optional[str] = None


class ListingRead(ListingBase):
    id: int
    status: str
    created_at: datetime
    updated_at: datetime
    thumbnail_url: Optional[str] = None
    
    # --- 마켓플레이스 연동 정보 ---
    marketplace_links: List[ListingMarketplaceSchema] = []

    model_config = ConfigDict(from_attributes=True)