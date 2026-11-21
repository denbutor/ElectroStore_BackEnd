from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    products: Mapped[list["Product"]] = relationship("Product", back_populates="category")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    specifications: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )

    category: Mapped[Category | None] = relationship("Category", back_populates="products")

    @property
    def category_name(self) -> str | None:
        return self.category.name if self.category else None

# from datetime import datetime
# from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
# from sqlalchemy.dialects.postgresql import JSONB
# from sqlalchemy.orm import Mapped, mapped_column, relationship
# from app.db.base import Base
#
#
# class Category(Base):
#     __tablename__ = "categories"
#
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
#     name: Mapped[str] = mapped_column(String(255), nullable=False)
#     slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
#
#     products: Mapped[list["Product"]] = relationship("Product", back_populates="category")
#
#
# class Product(Base):
#     __tablename__ = "products"
#
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
#     title: Mapped[str] = mapped_column(String(255), nullable=False)
#     description: Mapped[str | None] = mapped_column(Text, nullable=True)
#     price: Mapped[float] = mapped_column(Float, nullable=False)
#     stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
#     category_id: Mapped[int | None] = mapped_column(
#         Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
#     )
#     specifications: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
#     image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
#     is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
#     created_at: Mapped[datetime] = mapped_column(
#         DateTime(timezone=True), server_default=func.now()
#     )
#
#     category: Mapped[Category | None] = relationship("Category", back_populates="products")
#
#     @property
#     def category_name(self) -> str | None:
#         return self.category.name if self.category else None
#
# # from datetime import datetime
# # from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
# # from sqlalchemy.dialects.postgresql import JSONB
# # from sqlalchemy.orm import Mapped, mapped_column, relationship
# # from app.db.base import Base
# #
# #
# # class Category(Base):
# #     __tablename__ = "categories"
# #
# #     id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
# #     name: Mapped[str] = mapped_column(String(255), nullable=False)
# #     slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
# #
# #     products: Mapped[list["Product"]] = relationship("Product", back_populates="category")
# #
# #
# # class Product(Base):
# #     __tablename__ = "products"
# #
# #     id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
# #     title: Mapped[str] = mapped_column(String(255), nullable=False)
# #     description: Mapped[str | None] = mapped_column(Text, nullable=True)
# #     price: Mapped[float] = mapped_column(Float, nullable=False)
# #     stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
# #     category_id: Mapped[int | None] = mapped_column(
# #         Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
# #     )
# #     specifications: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
# #     image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
# #     is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
# #     created_at: Mapped[datetime] = mapped_column(
# #         DateTime(timezone=True), server_default=func.now()
# #     )
# #
# #     category: Mapped[Category | None] = relationship("Category", back_populates="products")
# #
# #     @property
# #     def category_name(self) -> str | None:
# #         return self.category.name if self.category else None
# #
# # # from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
# # # from sqlalchemy.dialects.postgresql import JSONB
# # # from sqlalchemy.orm import Mapped, mapped_column, relationship
# # # from app.db.base import Base
# # #
# # #
# # # class Category(Base):
# # #     __tablename__ = "categories"
# # #
# # #     id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
# # #     name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
# # #     slug: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
# # #
# # #     products = relationship("Product", back_populates="category")
# # #
# # #
# # # class Product(Base):
# # #     __tablename__ = "products"
# # #
# # #     id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
# # #     title: Mapped[str] = mapped_column(String, index=True, nullable=False)
# # #     description: Mapped[str] = mapped_column(String, nullable=True)
# # #     price: Mapped[float] = mapped_column(Float, nullable=False)
# # #     stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
# # #
# # #     # Характеристики як JSON (наприклад: {"socket": "AM5", "ram": "DDR5"})
# # #     specifications: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
# # #     image_url: Mapped[str | None] = mapped_column(String, nullable=True)
# # #
# # #     # Soft Delete
# # #     is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
# # #
# # #     category_id: Mapped[int] = mapped_column(Integer, ForeignKey("categories.id"))
# # #     category = relationship("Category", back_populates="products")
# # #
# # #     @property
# # #     def category_name(self) -> str | None:
# # #         return self.category.name if self.category else None
# # #
# # # # from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
# # # # from sqlalchemy.dialects.postgresql import JSONB
# # # # from sqlalchemy.orm import Mapped, mapped_column, relationship
# # # # from app.db.base import Base
# # # #
# # # #
# # # # class Category(Base):
# # # #     __tablename__ = "categories"
# # # #
# # # #     id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
# # # #     name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
# # # #     slug: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
# # # #
# # # #     products = relationship("Product", back_populates="category")
# # # #
# # # #
# # # # class Product(Base):
# # # #     __tablename__ = "products"
# # # #
# # # #     id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
# # # #     title: Mapped[str] = mapped_column(String, index=True, nullable=False)
# # # #     description: Mapped[str] = mapped_column(String, nullable=True)
# # # #     price: Mapped[float] = mapped_column(Float, nullable=False)
# # # #     stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
# # # #
# # # #     # Характеристики як JSON (наприклад: {"socket": "AM5", "ram": "DDR5"})
# # # #     specifications: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
# # # #     image_url: Mapped[str | None] = mapped_column(String, nullable=True)
# # # #
# # # #     # Soft Delete
# # # #     is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
# # # #
# # # #     category_id: Mapped[int] = mapped_column(Integer, ForeignKey("categories.id"))
# # # #     category = relationship("Category", back_populates="products")
# # # #
# # # #     @property
# # # #     def category_name(self) -> str | None:
# # # #         return self.category.name if self.category else None
# # # #
# # # # # from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
# # # # # from sqlalchemy.dialects.postgresql import JSONB
# # # # # from sqlalchemy.orm import Mapped, mapped_column, relationship
# # # # # from app.db.base import Base
# # # # #
# # # # #
# # # # # class Category(Base):
# # # # #     __tablename__ = "categories"
# # # # #
# # # # #     id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
# # # # #     name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
# # # # #
# # # # #     products = relationship("Product", back_populates="category")
# # # # #
# # # # #
# # # # # class Product(Base):
# # # # #     __tablename__ = "products"
# # # # #
# # # # #     id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
# # # # #     title: Mapped[str] = mapped_column(String, index=True, nullable=False)
# # # # #     description: Mapped[str] = mapped_column(String, nullable=True)
# # # # #     price: Mapped[float] = mapped_column(Float, nullable=False)
# # # # #     stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
# # # # #
# # # # #     # Характеристики як JSON (наприклад: {"socket": "AM5", "ram": "DDR5"})
# # # # #     specifications: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
# # # # #     image_url: Mapped[str | None] = mapped_column(String, nullable=True)
# # # # #
# # # # #     # Soft Delete
# # # # #     is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
# # # # #
# # # # #     category_id: Mapped[int] = mapped_column(Integer, ForeignKey("categories.id"))
# # # # #     category = relationship("Category", back_populates="products")
# # # # #
# # # # #     @property
# # # # #     def category_name(self) -> str | None:
# # # # #         return self.category.name if self.category else None
# # # # #
# # # # # # from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
# # # # # # from sqlalchemy.dialects.postgresql import JSONB
# # # # # # from sqlalchemy.orm import Mapped, mapped_column, relationship
# # # # # # from app.db.base import Base
# # # # # #
# # # # # # class Category(Base):
# # # # # #     __tablename__ = "categories"
# # # # # #
# # # # # #     id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
# # # # # #     name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
# # # # # #
# # # # # #     products = relationship("Product", back_populates="category")
# # # # # #
# # # # # # class Product(Base):
# # # # # #     __tablename__ = "products"
# # # # # #
# # # # # #     id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
# # # # # #     title: Mapped[str] = mapped_column(String, index=True, nullable=False)
# # # # # #     description: Mapped[str] = mapped_column(String, nullable=True)
# # # # # #     price: Mapped[float] = mapped_column(Float, nullable=False)
# # # # # #     stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
# # # # # #
# # # # # #     # Характеристики як JSON (наприклад: {"socket": "AM5", "ram": "DDR5"})
# # # # # #     specifications: Mapped[dict] = mapped_column(JSONB, default=dict, server_default='{}')
# # # # # #     image_url: Mapped[str | None] = mapped_column(String, nullable=True)
# # # # # #
# # # # # #     # Soft Delete
# # # # # #     is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
# # # # # #
# # # # # #     category_id: Mapped[int] = mapped_column(Integer, ForeignKey("categories.id"))
# # # # # #     category = relationship("Category", back_populates="products")