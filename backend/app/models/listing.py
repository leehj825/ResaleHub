from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Numeric,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    price = Column(Numeric(10, 2), nullable=False, default=0)
    currency = Column(String(3), nullable=False, default="USD")

    status = Column(String(20), nullable=False, default="draft")

    # ✅ 썸네일 이미지 URL (선택)
    thumbnail_url = Column(String(512), nullable=True)

    # [추가됨] SKU 및 상태 (Import 기능 지원)
    sku = Column(String(100), nullable=True)
    condition = Column(String(50), nullable=False, default="USED_GOOD")
    
    # eBay-specific fields
    ebay_category_id = Column(String(50), nullable=True)
    brand = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    owner = relationship("User", back_populates="listings")

    # ListingImage와의 관계
    images = relationship(
        "ListingImage",
        back_populates="listing",
        cascade="all, delete-orphan",
        order_by="ListingImage.sort_order",
    )
    
    # 마켓플레이스 연동 정보 관계
    marketplace_links = relationship(
        "ListingMarketplace",
        back_populates="listing",
        cascade="all, delete-orphan",
    )