from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://mailapp:mailapp_secure_2024@localhost:5432/maildb"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "change-this-to-a-random-secret-key-in-production"
    encryption_key: str = ""
    admin_username: str = "admin"
    admin_password: str = "mountainlion1024"
    claude_api_key: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8080/api/auth/google/callback"
    allowed_origins: str = "http://localhost:8080"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    attachment_storage_path: str = "/opt/mail/data/attachments"
    sync_interval_seconds: int = 60

    model_config = {"env_file": "/opt/mail/.env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
