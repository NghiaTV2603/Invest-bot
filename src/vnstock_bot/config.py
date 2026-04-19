from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id_whitelist: str = Field(..., alias="TELEGRAM_CHAT_ID_WHITELIST")

    initial_capital_vnd: int = Field(100_000_000, alias="INITIAL_CAPITAL_VND")
    fee_buy_bps: int = Field(15, alias="FEE_BUY_BPS")
    fee_sell_bps: int = Field(25, alias="FEE_SELL_BPS")

    db_path: Path = Field(Path("data/bot.db"), alias="DB_PATH")
    raw_data_dir: Path = Field(Path("data/raw"), alias="RAW_DATA_DIR")
    memory_dir: Path = Field(Path("data/memory"), alias="MEMORY_DIR")
    log_dir: Path = Field(Path("logs"), alias="LOG_DIR")

    tz: str = Field("Asia/Ho_Chi_Minh", alias="TZ")
    daily_cron_hour: int = Field(15, alias="DAILY_CRON_HOUR")
    daily_cron_minute: int = Field(30, alias="DAILY_CRON_MINUTE")
    weekly_cron_day: str = Field("sun", alias="WEEKLY_CRON_DAY")
    weekly_cron_hour: int = Field(10, alias="WEEKLY_CRON_HOUR")

    claude_model: str = Field("claude-sonnet-4-6", alias="CLAUDE_MODEL")
    claude_max_turns: int = Field(20, alias="CLAUDE_MAX_TURNS")
    claude_daily_token_budget: int = Field(40_000, alias="CLAUDE_DAILY_TOKEN_BUDGET")

    # v2: which daily research path the scheduler uses.
    # "single" = v1 single-agent (research.agent.daily_research)
    # "swarm"  = v2 orchestrator (daily_research preset via run_preset)
    daily_research_mode: Literal["single", "swarm"] = Field(
        "single", alias="DAILY_RESEARCH_MODE",
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field("INFO", alias="LOG_LEVEL")

    @property
    def whitelist_ids(self) -> set[int]:
        return {int(x.strip()) for x in self.telegram_chat_id_whitelist.split(",") if x.strip()}

    @property
    def absolute_db_path(self) -> Path:
        return self.db_path if self.db_path.is_absolute() else PROJECT_ROOT / self.db_path

    @property
    def absolute_raw_dir(self) -> Path:
        return self.raw_data_dir if self.raw_data_dir.is_absolute() else PROJECT_ROOT / self.raw_data_dir

    @property
    def absolute_memory_dir(self) -> Path:
        return self.memory_dir if self.memory_dir.is_absolute() else PROJECT_ROOT / self.memory_dir

    @property
    def absolute_log_dir(self) -> Path:
        return self.log_dir if self.log_dir.is_absolute() else PROJECT_ROOT / self.log_dir

    @property
    def watchlist_path(self) -> Path:
        return PROJECT_ROOT / "config" / "watchlist.yaml"

    @property
    def skills_dir(self) -> Path:
        return PROJECT_ROOT / "skills"

    @property
    def strategy_path(self) -> Path:
        return PROJECT_ROOT / "strategy.md"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.absolute_db_path.parent.mkdir(parents=True, exist_ok=True)
        _settings.absolute_raw_dir.mkdir(parents=True, exist_ok=True)
        _settings.absolute_memory_dir.mkdir(parents=True, exist_ok=True)
        _settings.absolute_log_dir.mkdir(parents=True, exist_ok=True)
    return _settings
