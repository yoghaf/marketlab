from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    env: str = "development"
    database_url: str = "sqlite:///./data/marketlab.db"
    log_level: str = "INFO"
    binance_timeout_seconds: float = 15
    binance_max_retries: int = 2
    binance_safe_used_weight_per_minute: int = 1000
    universe_limit: int = 75
    active_full_limit: int = 75
    light_watch_limit: int = 0
    collector_interval_seconds: int = Field(
        default=120,
        validation_alias=AliasChoices("COLLECTOR_INTERVAL_SECONDS", "MARKETLAB_COLLECTOR_INTERVAL_SECONDS"),
    )

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_prefix="MARKETLAB_",
        extra="ignore",
    )

    @property
    def normalized_database_url(self) -> str:
        if self.database_url.startswith("sqlite:///./"):
            return "sqlite:///" + str(ROOT_DIR / self.database_url.replace("sqlite:///./", ""))
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    loaded = Settings()
    loaded.database_url = loaded.normalized_database_url
    return loaded


settings = get_settings()
