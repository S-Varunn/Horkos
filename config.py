from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Discord Settings
    discord_token: str = Field(default="", alias="DISCORD_TOKEN")

    # LLM Settings (Hermes / OpenAI-compatible endpoint)
    llm_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        alias="LLM_BASE_URL"
    )
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(
        default="nousresearch/hermes-3-llama-3.1-70b",
        alias="LLM_MODEL"
    )

    # Database
    database_path: str = Field(default="commitment_radar.db", alias="DATABASE_PATH")

    # Scheduler Settings
    default_timezone: str = Field(default="America/New_York", alias="DEFAULT_TIMEZONE")
    alert_advance_minutes: int = Field(default=10, alias="ALERT_ADVANCE_MINUTES")
    check_interval_seconds: int = Field(default=30, alias="CHECK_INTERVAL_SECONDS")

    # Google Calendar Settings
    google_calendar_enabled: bool = Field(default=True, alias="GOOGLE_CALENDAR_ENABLED")
    google_credentials_file: str = Field(default="credentials.json", alias="GOOGLE_CREDENTIALS_FILE")
    google_token_file: str = Field(default="token.json", alias="GOOGLE_TOKEN_FILE")
    google_service_account_file: str = Field(default="", alias="GOOGLE_SERVICE_ACCOUNT_FILE")
    google_calendar_id: str = Field(default="primary", alias="GOOGLE_CALENDAR_ID")
    auto_schedule_calendar: bool = Field(default=True, alias="AUTO_SCHEDULE_CALENDAR")
    calendar_reminder_minutes: str = Field(default="30,10", alias="CALENDAR_REMINDER_MINUTES")
    google_oauth_port: int = Field(default=8080, alias="GOOGLE_OAUTH_PORT")
    google_oauth_redirect_uri: str = Field(
        default="http://localhost:8080/oauth/callback",
        alias="GOOGLE_OAUTH_REDIRECT_URI"
    )


settings = Settings()
