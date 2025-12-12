# backend/app/models/connect_token.py

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from datetime import datetime
from app.core.database import Base

class ConnectToken(Base):
    __tablename__ = "connect_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(128), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
