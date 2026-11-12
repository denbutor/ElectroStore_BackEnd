from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str
    POSTGRES_PORT: int = 5432
    ORDER_DB_NAME: str

    REDIS_HOST: str
    REDIS_PORT: int = 6379

    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"

    # URL для зв'язку з мікросервісом каталогу
    CATALOG_SERVICE_URL: str = "http://catalog_service:8000/api/v1"

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.ORDER_DB_NAME}"
        )

    @property
    def REDIS_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")

settings = Settings()