from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

_DEFAULT_DATA_DIR = Path.home() / ".samwise"


class Settings(BaseSettings):
    github_token: str = ""
    github_username: str = ""
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    host: str = "127.0.0.1"
    port: int = 9474
    poll_interval_seconds: int = 120
    data_dir: Path = _DEFAULT_DATA_DIR
    auto_merge: bool = False
    auto_fix_lint: bool = True
    google_client_secret_file: str = ""
    project_repos: list[str] = []
    project_staleness_days: int = 5
    pr_sla_max_lines: int = 600
    pr_sla_max_age_days: int = 7
    pr_sla_max_turns_before_review: int = 2
    workspace_roots: list[str] = []

    model_config = {"env_prefix": "SAMWISE_", "env_file": ".env"}
