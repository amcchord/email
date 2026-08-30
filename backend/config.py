from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = ""
    encryption_key: str = ""
    admin_username: str = "admin"
    admin_password: str = ""
    claude_api_key: str = ""
    openai_api_key: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8080/api/auth/google/callback"
    allowed_origins: str = "http://localhost:8080"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    attachment_storage_path: str = "/opt/mail/data/attachments"
    terminal_firmware_storage_path: str = "/opt/mail/data/terminal-firmware"
    terminal_firmware_trusted_signing_keys: str = "{}"
    terminal_firmware_minimum_catalog_generation: int = 0
    terminal_firmware_browser_flash_enabled: bool = False
    # Device OTA is independent from browser flashing. It remains locked until
    # an exact signed descriptor, parent release evidence, physical HIL
    # qualification, and durable server-side event persistence all agree.
    terminal_ota_enabled: bool = False
    terminal_ota_qualified_releases: str = "{}"
    # RET1 enrollment is an independent trust boundary from offline firmware
    # release signing. Production defaults remain locked until an operator
    # supplies an exact HTTPS base URL, an online P-256 key via a protected
    # file, and a release/model HIL allowlist.
    terminal_enrollment_enabled: bool = False
    terminal_enrollment_base_url: str = ""
    terminal_enrollment_signing_key_id: str = ""
    terminal_enrollment_private_key_path: str = ""
    terminal_enrollment_qualified_releases: str = "{}"
    terminal_enrollment_ticket_ttl_seconds: int = 300
    brave_search_api_key: str = ""
    sync_interval_seconds: int = 60

    model_config = {"env_file": "/opt/mail/.env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
