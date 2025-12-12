from datetime import datetime, timedelta
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from app.core.database import Base


class PairingCode(Base):
    __tablename__ = "pairing_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(6), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Status tracking
    is_used = Column(Boolean, default=False, nullable=False)
    cookies_received = Column(Boolean, default=False, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    
    # Relationship
    user = relationship("User", backref="pairing_codes")

