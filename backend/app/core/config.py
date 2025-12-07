from functools import lru_cache
from pydantic_settings import BaseSettings  # 🔹 여기 변경


class Settings(BaseSettings):
    app_name: str = "ResaleHub AI"
    app_env: str = "dev"
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60  # 🔹 철자도 exp*i*re 로 통일
    database_url: str

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
