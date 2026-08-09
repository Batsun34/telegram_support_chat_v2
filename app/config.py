import json
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(alias="BOT_TOKEN")
    database_url: str = Field(default="sqlite+aiosqlite:///./support_chat.db", alias="DATABASE_URL")
    moderators_json: str = Field(default="{}", alias="MODERATORS_JSON")
    admin_ids: str = Field(default="", alias="ADMIN_IDS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    debounce_seconds: float = Field(default=10.0, alias="DEBOUNCE_SECONDS")
    history_page_size: int = Field(default=10, alias="HISTORY_PAGE_SIZE")
    chat_list_page_size: int = Field(default=10, alias="CHAT_LIST_PAGE_SIZE")
    active_hours: int = Field(default=24, alias="ACTIVE_HOURS")
    view_ttl_hours: int = Field(default=23, alias="VIEW_TTL_HOURS")

    @property
    def moderators(self) -> dict[int, str]:
        raw = json.loads(self.moderators_json or "{}")
        return {
            int(key): (str(value).strip() or f"Модератор {key}")
            for key, value in raw.items()
        }

    @property
    def admins(self) -> set[int]:
        return {int(x.strip()) for x in self.admin_ids.split(",") if x.strip()}

    @field_validator("database_url")
    @classmethod
    def validate_sqlite(cls, value: str) -> str:
        if not value.startswith("sqlite+aiosqlite://"):
            raise ValueError(
                "v2 рассчитан на SQLite через sqlite+aiosqlite, например "
                "sqlite+aiosqlite:///./support_chat.db"
            )
        return value

    @field_validator("history_page_size")
    @classmethod
    def validate_history_page_size(cls, value: int) -> int:
        if not 1 <= value <= 50:
            raise ValueError("HISTORY_PAGE_SIZE должен быть от 1 до 50")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
