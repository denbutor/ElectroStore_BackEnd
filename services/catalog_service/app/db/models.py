from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    
    products = relationship("Product", back_populates="category")

class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String, index=True, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Характеристики як JSON (наприклад: {"socket": "AM5", "ram": "DDR5"})
    specifications: Mapped[dict] = mapped_column(JSONB, default=dict, server_default='{}')
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    
    # Soft Delete
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    
    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("categories.id"))
    category = relationship("Category", back_populates="products")