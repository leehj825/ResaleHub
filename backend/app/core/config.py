from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# backend/ 폴더 기준 BASE_DIR
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    # 기본 앱 설정
    app_name: str = "ResaleHub AI"

    # .env 에서 APP_ENV=dev 같은 걸 쓰고 싶을 때 대비
    app_env: str = "dev"

    # 보안 / JWT / DB
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    database_url: str

    # 미디어(이미지) 저장용
    media_root: Path = BASE_DIR / "media"
    media_url: str = "/media"
    
    ebay_client_id: str
    ebay_client_secret: str
    ebay_redirect_uri: str
    ebay_environment: str = "sandbox"
    ebay_fulfillment_policy_id: str | None = None
    ebay_payment_policy_id: str | None = None
    ebay_return_policy_id: str | None = None

    # pydantic-settings v2 방식 설정
    model_config = SettingsConfigDict(
        env_file=".env",   # backend/.env 읽기
        extra="ignore",    # .env 에 정의돼있지만 필드에 없는 값은 무시
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
