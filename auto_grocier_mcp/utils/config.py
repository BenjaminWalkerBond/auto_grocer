"""Configuration management using Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # HEB Configuration
    heb_default_store: str | None = Field(
        default=None,
        description="Default HEB store ID for operations",
    )
    heb_graphql_url: str = Field(
        default="https://www.heb.com/graphql",
        description="HEB GraphQL API endpoint",
    )

    # Auth State
    auth_state_path: Path = Field(
        default=Path("~/.texas-grocery-mcp/auth.json").expanduser(),
        description="Path to Playwright auth state file",
    )

    # Redis Configuration
    redis_url: str | None = Field(
        default=None,
        description="Redis connection URL for caching",
    )

    # Observability
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level",
    )
    environment: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Deployment environment",
    )

    # Reliability
    retry_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Number of retry attempts for failed requests",
    )
    circuit_breaker_threshold: int = Field(
        default=5,
        ge=1,
        description="Failures before circuit breaker opens",
    )
    circuit_breaker_timeout: int = Field(
        default=30,
        ge=5,
        description="Seconds before circuit breaker attempts recovery",
    )

    # Throttling - SSR
    max_concurrent_ssr_searches: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Maximum concurrent SSR product searches",
    )
    min_ssr_delay_ms: int = Field(
        default=200,
        ge=0,
        le=5000,
        description="Minimum delay between SSR requests in milliseconds",
    )
    ssr_jitter_ms: int = Field(
        default=200,
        ge=0,
        le=1000,
        description="Random jitter added to SSR delay (0 to N ms)",
    )

    # Throttling - GraphQL
    max_concurrent_graphql: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum concurrent GraphQL API calls",
    )
    min_graphql_delay_ms: int = Field(
        default=100,
        ge=0,
        le=5000,
        description="Minimum delay between GraphQL requests in milliseconds",
    )
    graphql_jitter_ms: int = Field(
        default=100,
        ge=0,
        le=1000,
        description="Random jitter added to GraphQL delay (0 to N ms)",
    )

    # Throttling - Global
    throttling_enabled: bool = Field(
        default=True,
        description="Enable/disable request throttling globally",
    )

    # Session Auto-Refresh
    auto_refresh_enabled: bool = Field(
        default=True,
        description="Enable automatic session refresh before tool execution",
    )
    auto_refresh_threshold_hours: float = Field(
        default=4.0,
        ge=0.5,
        le=24.0,
        description="Refresh session when less than this many hours remaining",
    )
    auto_refresh_on_startup: bool = Field(
        default=False,
        description=(
            "Check and refresh session on MCP server startup (disabled by default - "
            "login should be explicit)"
        ),
    )

    def model_post_init(self, __context: Any) -> None:
        """Ensure auth state path is expanded."""
        if "~" in str(self.auth_state_path):
            object.__setattr__(
                self, "auth_state_path", Path(str(self.auth_state_path)).expanduser()
            )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
