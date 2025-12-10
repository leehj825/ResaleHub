from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from pydantic import BaseModel, ConfigDict, Field

class ListingMarketplaceSchema(BaseModel):
    marketplace: str
    external_url: Optional[str] = None
    status: str
    external_item_id: Optional[str] = None
    sku: Optional[str] = None
    offer_id: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class ListingBase(BaseModel):
    title: str = Field(max_length=255)
    description: Optional[str] = None
    price: Decimal = Field(ge=0)
    currency: str = Field(default="USD", max_length=3)
    
    sku: Optional[str] = None
    condition: Optional[str] = Field(default="USED_GOOD")
    ebay_category_id: Optional[str] = None
    brand: Optional[str] = None

class ListingCreate(ListingBase):
    # [추가] 이미지 저장을 위해 필드 추가
    thumbnail_url: Optional[str] = None 
    
    import_from_marketplace: Optional[str] = None
    import_external_id: Optional[str] = None
    import_url: Optional[str] = None

class ListingUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    price: Optional[Decimal] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, max_length=3)
    status: Optional[str] = None
    
    sku: Optional[str] = None
    condition: Optional[str] = None
    ebay_category_id: Optional[str] = None
    brand: Optional[str] = None

class ListingRead(ListingBase):
    id: int
    status: str
    created_at: datetime
    updated_at: datetime
    thumbnail_url: Optional[str] = None
    
    marketplace_links: List[ListingMarketplaceSchema] = []

    model_config = ConfigDict(from_attributes=True)