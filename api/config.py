"""
Settings for the API, read once from the environment (and the project-root .env).

    APP_API_KEY           when set, every /api/* call needs header X-API-Key with this value
    RATE_LIMIT_PER_MIN    /api/ask calls allowed per client per minute (default 30)
    CORS_ORIGINS          comma-separated browser origins allowed (default the Streamlit UI)
    DB_PATH               the "default" dataset (default db/tickets.sqlite)
    DB_LARGE_PATH         the "large" dataset (default db/tickets_large.sqlite)
    AUDIT_LOG             where /api/ask calls are recorded (default logs/audit.jsonl)
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for folder in ("agent", "semantics", "evals"):
    if str(ROOT / folder) not in sys.path:
        sys.path.insert(0, str(ROOT / folder))

from llm import load_env  # noqa: E402


def _path(env_name, default):
    value = os.getenv(env_name)
    path = Path(value) if value else ROOT / default
    return path if path.is_absolute() else ROOT / path


@dataclass
class Settings:
    api_key: str | None
    rate_limit_per_min: int
    cors_origins: list[str]
    datasets: dict[str, Path]
    golden_sets: dict[str, Path]
    audit_log: Path
    version: str = "1.0.0"


def load_settings():
    load_env()
    origins = os.getenv("CORS_ORIGINS", "http://localhost:8501,http://127.0.0.1:8501")
    return Settings(
        api_key=os.getenv("APP_API_KEY") or None,
        rate_limit_per_min=int(os.getenv("RATE_LIMIT_PER_MIN", "30")),
        cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
        datasets={"default": _path("DB_PATH", "db/tickets.sqlite"),
                  "large": _path("DB_LARGE_PATH", "db/tickets_large.sqlite")},
        golden_sets={"golden_set.yaml": ROOT / "evals" / "golden_set.yaml",
                     "golden_set_large.yaml": ROOT / "evals" / "golden_set_large.yaml"},
        audit_log=_path("AUDIT_LOG", "logs/audit.jsonl"),
    )
