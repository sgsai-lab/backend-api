from functools import lru_cache
from typing import Literal, Self

from pydantic import PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "development", "staging", "production"]
_EPHEMERAL_KEY_ENVIRONMENTS = {"local", "test"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "sgsai-backend-api"
    environment: Environment = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True
    port: int = 8080
    gcp_project_id: str | None = None
    max_request_body_bytes: int = 1_048_576

    database_url: PostgresDsn
    db_pool_size: int = 5
    db_max_overflow: int = 0

    cors_allow_origins: list[str] = []
    frontend_base_url: str = "http://localhost:3000"

    jwt_private_key: SecretStr | None = None
    jwt_key_id: str = "local-1"
    jwt_previous_public_key: SecretStr | None = None
    jwt_previous_key_id: str | None = None
    jwt_issuer: str = "sgsai-backend-api"
    jwt_audience: str = "sgsai-clients"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_days: int = 30
    refresh_token_absolute_ttl_days: int = 90

    mfa_encryption_key: SecretStr | None = None
    mfa_issuer: str = "SGS AI"
    # Feature flags: MFA is optional until production hardening.
    mfa_enabled: bool = True
    admin_require_mfa: bool = False

    google_oauth_client_ids: list[str] = []

    email_backend: Literal["smtp", "api", "memory"] = "smtp"
    email_from: str = "SGS AI <no-reply@sgsai.local>"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_start_tls: bool = False
    email_api_url: str = "https://api.sendgrid.com/v3/mail/send"
    email_api_key: SecretStr | None = None
    email_timeout_seconds: float = 5.0

    rate_limit_enabled: bool = True

    @property
    def docs_enabled(self) -> bool:
        return self.environment != "production"

    @property
    def allows_ephemeral_keys(self) -> bool:
        return self.environment in _EPHEMERAL_KEY_ENVIRONMENTS

    @model_validator(mode="after")
    def _require_secrets_outside_local(self) -> Self:
        if self.allows_ephemeral_keys:
            return self
        missing = [
            name
            for name in ("jwt_private_key", "mfa_encryption_key")
            if getattr(self, name) is None
        ]
        if self.email_backend == "api" and self.email_api_key is None:
            missing.append("email_api_key")
        if missing:
            raise ValueError(f"Missing required settings for {self.environment}: {missing}")
        return self


@lru_cache
def get_settings() -> Settings:
    # Raises ValidationError at startup if required config is missing.
    return Settings()
