"""Central configuration. Secrets come ONLY from environment variables / .env."""
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Fixed "current time" used by the evaluation so results are reproducible.
EVAL_NOW = datetime(2026, 10, 6, 6, 0)  # Tuesday 06:00


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "").strip()
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    use_llm: bool = _bool("USE_LLM", True)
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.0"))
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
    llm_max_tokens: int = 600
    prompt_version: str = os.getenv("PROMPT_VERSION", "v2")
    db_path: str = str(BASE_DIR / os.getenv("DB_PATH", "data/calendar.db"))
    scheduler_interval: int = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "10"))
    max_input_chars: int = 500
    dataset_path: str = str(BASE_DIR / "data" / "evaluation_dataset.csv")
    results_dir: str = str(BASE_DIR / "evaluation" / "results")

    @property
    def llm_configured(self) -> bool:
        return bool(self.anthropic_api_key) and self.anthropic_api_key != "your_key_here"


settings = Settings()
