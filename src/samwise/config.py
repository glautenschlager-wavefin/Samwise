from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

_DEFAULT_DATA_DIR = Path.home() / ".samwise"


class Settings(BaseSettings):
    github_token: str = ""
    github_username: str = ""
    host: str = "127.0.0.1"
    port: int = 9474
    poll_interval_seconds: int = 120
    data_dir: Path = _DEFAULT_DATA_DIR
    auto_merge: bool = False

    model_config = {"env_prefix": "SAMWISE_"}
