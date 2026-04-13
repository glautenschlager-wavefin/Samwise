from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    github_token: str = ""
    github_username: str = ""
    host: str = "127.0.0.1"
    port: int = 9474
    poll_interval_seconds: int = 120

    model_config = {"env_prefix": "SAMWISE_"}
