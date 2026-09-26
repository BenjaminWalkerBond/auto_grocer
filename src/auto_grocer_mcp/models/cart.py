"""Cart data models."""

from pydantic import BaseModel, Field, computed_field


class CartItem(BaseModel):
    """Item in shopping cart."""

    sku: str = Field(description="Product SKU")
    name: str = Field(description="Product name")
    price: float = Field(description="Unit price")
    quantity: int = Field(ge=1, description="Quantity in cart")
    image_url: str | None = Field(default=None, description="Product image")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def subtotal(self) -> float:
        """Calculate item subtotal."""
        return round(self.price * self.quantity, 2)


class AppliedCoupon(BaseModel):
    """Coupon applied to cart."""

    code: str = Field(description="Coupon code")
    discount: float = Field(description="Discount amount")
    description: str | None = Field(default=None, description="Coupon description")


class Cart(BaseModel):
    """Shopping cart."""

    items: list[CartItem] = Field(default_factory=list, description="Cart items")
    coupons_applied: list[AppliedCoupon] = Field(
        default_factory=list, description="Applied coupons"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def subtotal(self) -> float:
        """Calculate cart subtotal before coupons."""
        return round(sum(item.subtotal for item in self.items), 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_discount(self) -> float:
        """Calculate total coupon discount."""
        return round(sum(c.discount for c in self.coupons_applied), 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def estimated_total(self) -> float:
        """Calculate estimated total after discounts."""
        return round(self.subtotal - self.total_discount, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def item_count(self) -> int:
        """Total number of items in cart."""
        return sum(item.quantity for item in self.items)
