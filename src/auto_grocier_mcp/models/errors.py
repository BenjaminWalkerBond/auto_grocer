"""Error response models."""

from typing import Literal

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Structured error response."""

    error: bool = Field(default=True, description="Always true for errors")
    code: str = Field(description="Error code (e.g., HEB_API_TIMEOUT)")
    category: Literal["client", "server", "external"] = Field(
        description="Error category for handling"
    )
    message: str = Field(description="Human-readable error message")
    retry_after_seconds: int | None = Field(
        default=None, description="Seconds to wait before retry"
    )
    fallback_used: bool = Field(
        default=False, description="Whether fallback data source was used"
    )
    fallback_source: str | None = Field(
        default=None, description="Which fallback was used (cache, scraper)"
    )
    suggestions: list[str] = Field(
        default_factory=list, description="Actionable suggestions"
    )


class AuthRequiredResponse(BaseModel):
    """Response when authentication is required."""

    auth_required: bool = Field(default=True)
    message: str = Field(default="Login required for this operation")
    instructions: list[str] = Field(
        default_factory=lambda: [
            "1. Use Playwright MCP: browser_navigate to 'https://www.heb.com/my-account/login'",
            "2. Complete login in the browser",
            "3. Use Playwright MCP: browser_run_code to save storage state",
            "4. Retry this operation",
        ]
    )
