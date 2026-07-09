"""Application configuration loaded from environment / .env.

Phase 1: only the values needed to boot are required at runtime. Service
keys are read lazily by their respective clients so the skeleton can start
without a fully populated .env.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_anon_key: str = ""

    # AI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-2024-11-20"
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    # Auth
    jwt_secret: str = ""

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""

    # Web Push
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""

    # Email briefings (Resend)
    resend_api_key: str = ""
    briefing_from_email: str = ""
    briefing_to_emails_raw: str = Field(
        default="", validation_alias="BRIEFING_TO_EMAILS"
    )
    # Weekday the weekly cohort digest sends on (0=Mon … 6=Sun). The cron runs
    # daily; the digest only fires when today matches this.
    briefing_digest_weekday: int = 0

    # App
    cors_origins_raw: str = Field(
        default="http://localhost:5173", validation_alias="CORS_ORIGINS"
    )
    internal_cron_secret: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    @property
    def briefing_to_emails(self) -> list[str]:
        return [
            e.strip() for e in self.briefing_to_emails_raw.split(",") if e.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
