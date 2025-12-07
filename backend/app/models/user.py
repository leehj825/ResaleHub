from sqlalchemy import Column, Integer, String, DateTime, func

from sqlalchemy.orm import relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    listings = relationship(
        "Listing",
        back_populates="owner",
        cascade="all, delete-orphan",
    )

    marketplace_accounts = relationship(
        "MarketplaceAccount",
        back_populates="user",
        cascade="all, delete-orphan",
    )
