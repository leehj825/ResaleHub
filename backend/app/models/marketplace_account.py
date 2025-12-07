# backend/app/models/marketplace_account.py

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from datetime import datetime

from app.core.database import Base


class MarketplaceAccount(Base):
    __tablename__ = "marketplace_accounts"

    id = Column(Integer, primary_key=True, index=True)

    # User.id 와 연결
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # 'ebay' or 'poshmark'
    marketplace = Column(String(50), nullable=False)

    # 예: eBay user id, Poshmark username
    username = Column(String(255), nullable=True)

    # OAuth token 등
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # 🔥 여기 수정!
    user = relationship("User", back_populates="marketplace_accounts")
