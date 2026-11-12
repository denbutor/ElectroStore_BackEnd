from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class ProductVector(Base):
    __tablename__ = "products" # Вказуємо на існуючу таблицю в catalog_db

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    price: Mapped[float] = mapped_column(Float)
    stock: Mapped[int] = mapped_column(Integer)
    specifications: Mapped[dict] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean)
    
    # Векторне поле на 768 вимірів для сумісності з Google text-embedding-004
    embedding: Mapped[list[float]] = mapped_column(Vector(768), nullable=True)