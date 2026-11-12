# import asyncio
# import json
# import os
# from sqlalchemy.ext.asyncio import create_async_engine
# from sqlalchemy import text
# # from passlib.context import CryptContext
# import bcrypt

# # pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# # Отримуємо доступи з оточення контейнера
# DB_USER = os.getenv("POSTGRES_USER", "electro_admin")
# DB_PASS = os.getenv("POSTGRES_PASSWORD", "secret_password_123")
# DB_HOST = os.getenv("POSTGRES_HOST", "postgres")

# AUTH_DB_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:5432/auth_db"
# CATALOG_DB_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:5432/catalog_db"

# async def seed_auth():
#     engine = create_async_engine(AUTH_DB_URL)
#     async with engine.begin() as conn:
#         print("Seeding Admin User...")
#         # hashed_pw = pwd_context.hash("admin123")
#         raw_password = b"adminpassword123"
#         hashed_pw = bcrypt.hashpw(raw_password, bcrypt.gensalt()).decode("utf-8")
#         await conn.execute(
#             text("""
#             INSERT INTO users (email, hashed_password, full_name, role, is_active) 
#             VALUES (:email, :pw, :name, :role, true)
#             ON CONFLICT (email) DO NOTHING
#             """),
#             {"email": "admin@electro.com", "pw": hashed_pw, "name": "System Admin", "role": "admin"}
#         )
#     await engine.dispose()

# async def seed_catalog():
#     engine = create_async_engine(CATALOG_DB_URL)
#     async with engine.begin() as conn:
#         print("Seeding Categories...")
#         await conn.execute(text("INSERT INTO categories (id, name) VALUES (1, 'Процесори'), (2, 'Материнські плати') ON CONFLICT DO NOTHING"))
        
#         print("Seeding Products...")
#         products = [
#             {
#                 "title": "AMD Ryzen 5 7600X",
#                 "description": "Потужний процесор для ігор",
#                 "price": 9500.00,
#                 "stock": 10,
#                 "category_id": 1,
#                 "specs": json.dumps({"socket": "AM5", "tdp": 105, "ram_type": "DDR5"})
#             },
#             {
#                 "title": "ASUS TUF GAMING B650-PLUS",
#                 "description": "Надійна плата формату ATX",
#                 "price": 8200.00,
#                 "stock": 5,
#                 "category_id": 2,
#                 "specs": json.dumps({"socket": "AM5", "form_factor": "ATX", "ram_type": "DDR5"})
#             }
#         ]
        
#         for p in products:
#             await conn.execute(
#                 text("""
#                 INSERT INTO products (title, description, price, stock, category_id, specifications, is_active)
#                 VALUES (:title, :description, :price, :stock, :category_id, :specs::jsonb, true)
#                 ON CONFLICT DO NOTHING
#                 """),
#                 p
#             )
#     await engine.dispose()

# async def main():
#     try:
#         await seed_auth()
#         await seed_catalog()
#         print("✅ Database seeding completed successfully!")
#     except Exception as e:
#         print(f"❌ Seeding failed: {e}")

# if __name__ == "__main__":
#     asyncio.run(main())

import asyncio
import json
import os
import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DB_USER = os.getenv("POSTGRES_USER", "electro_admin")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "secret_password_123")
DB_HOST = os.getenv("POSTGRES_HOST", "postgres")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
AUTH_DB = os.getenv("AUTH_DB_NAME", "auth_db")
CATALOG_DB = os.getenv("CATALOG_DB_NAME", "catalog_db")

AUTH_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{AUTH_DB}"
CATALOG_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{CATALOG_DB}"


async def seed():
    try:
        # 1. Створюємо адміністратора в auth_db
        print("Seeding Admin User...")
        auth_engine = create_async_engine(AUTH_URL)
        async with auth_engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    hashed_password VARCHAR(255) NOT NULL,
                    role VARCHAR(50) NOT NULL DEFAULT 'user',
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """))

            raw_password = b"adminpassword123"
            hashed_pwd = bcrypt.hashpw(raw_password, bcrypt.gensalt()).decode("utf-8")

            await conn.execute(
                text("""
                    INSERT INTO users (email, hashed_password, role, is_active)
                    VALUES (:email, :password, 'admin', true)
                    ON CONFLICT (email) DO NOTHING;
                """),
                {"email": "admin@electrostore.ua", "password": hashed_pwd}
            )
        await auth_engine.dispose()

        # 2. Наповнюємо catalog_db (категорії та товари)
        catalog_engine = create_async_engine(CATALOG_URL)
        async with catalog_engine.begin() as conn:
            print("Creating catalog tables...")
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS categories (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    slug VARCHAR(255) UNIQUE NOT NULL
                );
            """))

            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    description TEXT,
                    price NUMERIC(10, 2) NOT NULL,
                    stock INT NOT NULL DEFAULT 0,
                    category_id INT REFERENCES categories(id) ON DELETE SET NULL,
                    specifications JSONB NOT NULL DEFAULT '{}',
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """))

            print("Seeding Categories...")
            categories = [
                {"name": "Процесори", "slug": "cpus"},
                {"name": "Материнські плати", "slug": "motherboards"},
                {"name": "Відеокарти", "slug": "gpus"},
                {"name": "Оперативна пам'ять", "slug": "ram"}
            ]

            for cat in categories:
                await conn.execute(
                    text("""
                        INSERT INTO categories (name, slug)
                        VALUES (:name, :slug)
                        ON CONFLICT (slug) DO NOTHING;
                    """),
                    cat
                )

            print("Seeding Products...")
            products = [
                {
                    "title": "AMD Ryzen 5 7600X",
                    "description": "6 ядер, 12 потоків, базова частота 4.7 ГГц, сокет AM5.",
                    "price": 9500.00,
                    "stock": 15,
                    "category_id": 1,
                    "specifications": json.dumps({"socket": "AM5", "cores": 6, "tdp": "105W", "ddr": "DDR5"})
                },
                {
                    "title": "ASUS TUF GAMING B650-PLUS",
                    "description": "Материнська плата на чипсеті AMD B650 із сокетом AM5 та підтримкою DDR5.",
                    "price": 8200.00,
                    "stock": 8,
                    "category_id": 2,
                    "specifications": json.dumps({"socket": "AM5", "chipset": "B650", "form_factor": "ATX", "ram_slots": 4})
                },
                {
                    "title": "Kingston Fury Beast DDR5 32GB (2x16GB) 6000MHz",
                    "description": "Комплект швидкої оперативної пам'яті DDR5 з підтримкою AMD EXPO.",
                    "price": 5400.00,
                    "stock": 20,
                    "category_id": 4,
                    "specifications": json.dumps({"type": "DDR5", "capacity": "32GB", "speed": "6000MHz", "cl": 36})
                }
            ]

            for prod in products:
                await conn.execute(
                    text("""
                        INSERT INTO products (title, description, price, stock, category_id, specifications, is_active)
                        VALUES (:title, :description, :price, :stock, :category_id, CAST(:specifications AS jsonb), true);
                    """),
                    prod
                )

        await catalog_engine.dispose()
        print("✅ Database seeding completed successfully!")

    except Exception as e:
        print(f"❌ Seeding failed: {e}")


if __name__ == "__main__":
    asyncio.run(seed())