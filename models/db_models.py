"""SQLAlchemy ORM model for storing extraction records."""
from sqlalchemy import Column, String, Integer, Text, DateTime
from datetime import datetime
from database import Base
import uuid


class ExtractionDB(Base):
    __tablename__ = "extractions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    extraction_id = Column(String, unique=True, index=True)
    filename = Column(String)
    num_pages = Column(Integer, default=0)
    num_machines = Column(Integer, default=0)
    machines = Column(Text, default="[]")
    excel_files = Column(Text, default="[]")
    status = Column(String, default="completed")
    created_at = Column(DateTime, default=datetime.utcnow)