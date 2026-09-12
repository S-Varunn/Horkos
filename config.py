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
        default="nousresearch/hermes-3-llama-3.1-8b:free",
        alias="LLM_MODEL"
    )

    # Database
    database_path: str = Field(default="commitment_radar.db", alias="DATABASE_PATH")

    # Scheduler Settings
    default_timezone: str = Field(default="UTC", alias="DEFAULT_TIMEZONE")
    alert_advance_minutes: int = Field(default=30, alias="ALERT_ADVANCE_MINUTES")
    check_interval_seconds: int = Field(default=30, alias="CHECK_INTERVAL_SECONDS")

    # Ambient Dining Assistant Settings
    dining_inquiry_timeout_seconds: int = Field(default=15, alias="DINING_INQUIRY_TIMEOUT_SECONDS")
    dining_history_window_minutes: int = Field(default=3, alias="DINING_HISTORY_WINDOW_MINUTES")
    accepted_plan_memory_hours: int = Field(default=4, alias="ACCEPTED_PLAN_MEMORY_HOURS")
    default_location: str = Field(default="New York, NY", alias="DEFAULT_LOCATION")


settings = Settings()
