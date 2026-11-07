import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_env: str = "local"
    data_dir: str = "./data"
    artifact_uri: str = "./artifacts"
    log_uri: str = "./artifacts/logs/actions.jsonl"
    api_url: str = "http://127.0.0.1:8000"
    source: str = "mock"
    demo_token: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        defaults = cls()
        return cls(
            app_env=env.get("APP_ENV", defaults.app_env),
            data_dir=env.get("DATA_DIR", defaults.data_dir),
            artifact_uri=env.get("ARTIFACT_URI", defaults.artifact_uri),
            log_uri=env.get("LOG_URI", defaults.log_uri),
            api_url=env.get("API_URL", defaults.api_url),
            source=env.get("SOURCE", defaults.source),
            demo_token=env.get("DEMO_TOKEN") or None,
        )
