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

    # 실제 마켓플레이스 아이템 ID (나중에)
    external_item_id = Column(String(255), nullable=True)

    # 마켓플레이스 URL (나중에)
    external_url = Column(String(500), nullable=True)

    status = Column(String(50), nullable=False, default="published")  
    # e.g. 'published', 'failed', 'ended'

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    listing = relationship("Listing", back_populates="marketplace_links")
