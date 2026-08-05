"""Coupon data models."""

from pydantic import BaseModel, Field


class CouponCategory(BaseModel):
    """Coupon category/department."""

    id: int = Field(description="Category ID")
    name: str = Field(description="Category display name")
    count: int = Field(description="Number of coupons in this category")


class Coupon(BaseModel):
    """HEB digital coupon."""

    coupon_id: int = Field(description="Unique coupon identifier")
    headline: str = Field(description="Short discount headline (e.g., '25% off', '$2 off')")
    description: str = Field(description="Full description of eligible products")
    expires: str | None = Field(default=None, description="Expiration date (YYYY-MM-DD)")
    expires_display: str | None = Field(default=None, description="Human-readable expiration")
    image_url: str | None = Field(default=None, description="Coupon image URL")

    # Coupon type and status
    coupon_type: str = Field(default="NORMAL", description="Type: NORMAL, COMBO_LOCO, MEAL_DEAL")
    clipped: bool = Field(default=False, description="Whether user has clipped this coupon")
    redeemable: bool = Field(default=True, description="Whether coupon can be redeemed")

    # Usage info
    usage_limit: str | None = Field(default=None, description="Usage limit (e.g., 'Limit 1')")
    digital_only: bool = Field(default=False, description="Exclusive digital coupon")


class CouponSearchResult(BaseModel):
    """Result from coupon list/search."""

    coupons: list[Coupon] = Field(default_factory=list)
    count: int = Field(description="Number of coupons returned")
    total: int = Field(description="Total coupons available")
    page: int = Field(default=1, description="Current page number")
    categories: list[CouponCategory] = Field(
        default_factory=list,
        description="Available categories",
    )
