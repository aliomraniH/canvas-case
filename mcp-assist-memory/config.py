"""Single source of truth for configuration and secrets.

This is the ONLY place in the service that reads the environment. Everything
else imports the ``settings`` singleton. (Grep-gate: ``os.environ`` must not
appear outside this module.)
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- required ---
    database_url: str
    mcp_auth_token: str

    # --- declared now, used in Phase 3 (kept optional so the service boots without them) ---
    voyage_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    langsmith_api_key: str | None = None

    # --- artifact / bytea safety (see addendum #4) ---
    max_artifact_bytes: int = 50 * 1024 * 1024          # hard write cap: 50 MB
    artifact_inline_limit: int = 1 * 1024 * 1024        # MCP returns base64 inline only below this;
                                                        # larger blobs stream via GET /artifact/{sha256}
    artifact_stream_chunk: int = 1 * 1024 * 1024        # ranged read window for streamed blobs

    # --- pool / lifespan bounds (see addendum #1) ---
    pool_max_size: int = 10
    pool_timeout: float = 10.0                          # max wait to check out a conn
    pool_reconnect_timeout: float = 30.0
    pool_max_idle: float = 60.0
    db_connect_timeout: int = 10                        # libpq TCP/handshake cap (seconds)
    db_statement_timeout_ms: int = 15000
    readiness_timeout_s: float = 15.0                   # hard cap on boot readiness probe

    # --- server ---
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"


settings = Settings()  # import this; never read the environment elsewhere
