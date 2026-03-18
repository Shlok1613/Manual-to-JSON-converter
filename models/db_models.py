from sqlalchemy import Column, String, Integer
from database import Base
import uuid

class ExtractionDB(Base):
    __tablename__ = "extractions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    extraction_id = Column(String, unique=True)
    filename = Column(String)
    num_pages = Column(Integer)
    num_machines = Column(Integer)
    status = Column(String)
    uploaded_at = Column(String)