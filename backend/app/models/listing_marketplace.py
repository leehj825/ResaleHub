from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime

from app.core.database import Base


class ListingMarketplace(Base):
    __tablename__ = "listing_marketplaces"

    id = Column(Integer, primary_key=True, index=True)

    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False, index=True)

    # 'ebay' / 'poshmark'
    marketplace = Column(String(50), nullable=False)

    # eBay Item ID (Listing ID)
    external_item_id = Column(String(255), nullable=True)
    
    # [추가됨] Inventory 관리를 위한 SKU
    sku = Column(String(255), nullable=True)

    # [추가됨] eBay Offer ID
    offer_id = Column(String(255), nullable=True)

    # 실제 상품 URL (View on eBay 버튼용)
    external_url = Column(String(500), nullable=True)

    status = Column(String(50), nullable=False, default="published")  
    # e.g. 'published', 'active', 'failed', 'ended'

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    listing = relationship("Listing", back_populates="marketplace_links")
