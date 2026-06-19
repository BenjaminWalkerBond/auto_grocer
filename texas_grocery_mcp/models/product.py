"""Product data models."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProductNutrition(BaseModel):
    """Nutritional information."""

    calories: int | None = None
    protein: str | None = None
    carbohydrates: str | None = None
    fat: str | None = None
    fiber: str | None = None
    sodium: str | None = None


class ProductCoupon(BaseModel):
    """Coupon applicable to product."""

    code: str
    discount: str
    expires: str | None = None


# ============================================================================
# Product Details Models (for product_get tool)
# ============================================================================


class NutrientInfo(BaseModel):
    """Individual nutrient from FDA nutrition facts panel.

    Supports nested sub_items for nutrients like:
    - Total Fat -> Saturated Fat, Trans Fat, etc.
    - Total Carbohydrate -> Dietary Fiber, Total Sugars, etc.
    """

    title: str = Field(description="Nutrient name (e.g., 'Total Fat')")
    unit: str = Field(description="Amount with unit (e.g., '14g')")
    percentage: str | None = Field(default=None, description="% Daily Value (e.g., '18%')")
    font_modifier: str | None = Field(
        default=None, description="Display style: BOLD, PLAIN, ITALIC"
    )
    sub_items: list["NutrientInfo"] | None = Field(
        default=None, description="Nested nutrients (e.g., Saturated Fat under Total Fat)"
    )


class ExtendedNutrition(BaseModel):
    """Complete FDA-style nutrition facts panel.

    Matches the structure returned by HEB's nutritionLabels API field.
    """

    serving_size: str | None = Field(default=None, description="e.g., '1 Tbsp (15mL)'")
    servings_per_container: str | None = Field(default=None, description="e.g., 'about 34'")
    calories: str | None = Field(default=None, description="Calories per serving")
    label_modifier: str | None = Field(default=None, description="e.g., '15 mL'")
    nutrients: list[NutrientInfo] = Field(
        default_factory=list,
        description="Main nutrients (fat, cholesterol, sodium, carbs, protein)",
    )
    vitamins_and_minerals: list[NutrientInfo] = Field(
        default_factory=list, description="Vitamins and minerals section"
    )


class ProductDetails(BaseModel):
    """Comprehensive product information from HEB product detail page.

    Returned by the product_get tool. Contains all available details
    including ingredients, nutrition facts, warnings, and instructions.

    Note: Many fields are optional as availability varies by product type:
    - Food items: Have nutrition, ingredients, may have warnings
    - Produce: Have ingredients, dietary attributes, no nutrition panel
    - Non-food: Have chemical ingredients, extensive warnings, no nutrition
    """

    # === Identifiers ===
    product_id: str = Field(description="Product ID (e.g., '127074')")
    sku: str = Field(description="SKU ID (e.g., '4122071073')")
    upc: str | None = Field(default=None, description="12-digit UPC barcode")

    # === Basic Info ===
    name: str = Field(description="Full product display name")
    description: str | None = Field(
        default=None, description="Product description (may contain HTML)"
    )
    brand: str | None = Field(default=None, description="Brand name")
    is_own_brand: bool = Field(default=False, description="True if HEB own brand")

    # === Pricing & Availability ===
    price: float = Field(description="Curbside/delivery price")
    price_online: float | None = Field(default=None, description="In-store/online price")
    on_sale: bool = Field(default=False, description="Currently on sale")
    is_price_cut: bool = Field(default=False, description="Price cut active")
    available: bool = Field(description="In stock at store")
    price_per_unit: str | None = Field(default=None, description="e.g., '$0.41 / fl oz'")

    # === Size ===
    size: str | None = Field(default=None, description="Package size (e.g., '17 oz')")

    # === Ingredients ===
    ingredients: str | None = Field(
        default=None,
        description="Full ingredients text (string, not list)"
    )

    # === Safety Warning ===
    safety_warning: str | None = Field(
        default=None,
        description="Safety/allergen warnings (may include allergen info for food)"
    )

    # === Instructions ===
    instructions: str | None = Field(
        default=None,
        description="Preparation, storage, or usage instructions"
    )

    # === Dietary Attributes ===
    dietary_attributes: list[str] = Field(
        default_factory=list,
        description=(
            "Dietary info from lifestyles (e.g., 'Gluten free verified', "
            "'Organic', 'Vegan')"
        ),
    )

    # === Nutrition (only for packaged food) ===
    nutrition: ExtendedNutrition | None = Field(
        default=None,
        description="Full FDA nutrition panel (null for produce/non-food)"
    )

    # === Category ===
    category_path: list[str] = Field(
        default_factory=list,
        description="Category breadcrumb (e.g., ['Shop', 'Pantry', 'Oils'])"
    )

    # === Media ===
    image_url: str | None = Field(default=None, description="Primary product image URL")
    images: list[str] = Field(default_factory=list, description="All product image URLs")

    # === Store Location ===
    location: str | None = Field(
        default=None,
        description="Store location (e.g., 'Aisle 5' or 'In Produce')"
    )
    store_id: int | None = Field(default=None, description="Store ID for this data")

    # === Availability Channels ===
    availability_channels: list[str] = Field(
        default_factory=list,
        description="How product can be purchased (e.g., ['IN_STORE', 'CURBSIDE_PICKUP'])"
    )

    # === SNAP/EBT ===
    is_snap_eligible: bool = Field(default=False, description="SNAP EBT eligible")

    # === URL ===
    product_url: str | None = Field(default=None, description="Full URL to product page")


class Product(BaseModel):
    """HEB product information.

    IMPORTANT FOR CART OPERATIONS:
    - Use `product_id` as the first argument to cart_add
    - Use `sku` as the second argument (sku_id) to cart_add

    Example:
        cart_add(product_id=product.product_id, sku_id=product.sku, quantity=1)
    """

    # SKU - the longer identifier needed for cart operations
    sku: str = Field(description="SKU ID (longer numeric ID) - use as sku_id in cart_add")
    name: str = Field(description="Product name")
    price: float = Field(description="Current price")
    available: bool = Field(description="In stock at store")

    # Product ID - the shorter identifier needed for cart operations
    product_id: str | None = Field(
        default=None,
        description="Product ID (shorter numeric ID) - use as product_id in cart_add"
    )

    # Standard fields (optional)
    brand: str | None = Field(default=None, description="Brand name")
    size: str | None = Field(default=None, description="Package size")
    price_per_unit: str | None = Field(default=None, description="Unit price display")
    image_url: str | None = Field(default=None, description="Product image URL")
    aisle: str | None = Field(default=None, description="Store aisle number")
    section: str | None = Field(default=None, description="Store section")
    has_coupon: bool = Field(default=False, description="Coupon available for this product")

    # Extended fields (optional)
    nutrition: ProductNutrition | None = Field(default=None, description="Nutrition facts")
    ingredients: list[str] | None = Field(default=None, description="Ingredient list")
    on_sale: bool = Field(default=False, description="Currently on sale")
    original_price: float | None = Field(default=None, description="Price before sale")
    rating: float | None = Field(default=None, ge=0, le=5, description="Customer rating")
    coupons: list[ProductCoupon] = Field(
        default_factory=list, description="Applicable coupons"
    )


class ProductSearchAttempt(BaseModel):
    """Record of a product search attempt for diagnostics."""

    query: str = Field(description="Query string used")
    method: Literal["ssr", "typeahead_as_ssr", "typeahead"] = Field(
        description="Search method attempted"
    )
    result: Literal["success", "empty", "security_challenge", "error"] = Field(
        description="Result of the attempt"
    )
    error_detail: str | None = Field(default=None, description="Error details if failed")


class ProductSearchResult(BaseModel):
    """Result of a product search with diagnostic metadata.

    Provides transparency about the search process, including which methods
    were tried and why fallbacks were used.
    """

    # Core results
    products: list[Product] = Field(default_factory=list, description="Found products")
    count: int = Field(description="Number of products found")
    query: str = Field(description="Original search query")
    store_id: str = Field(description="Store ID used for search")

    # Data source tracking
    data_source: Literal["ssr", "playwright", "typeahead_suggestions"] = Field(
        description="Source of the product data"
    )
    authenticated: bool = Field(
        default=False, description="Whether authenticated search was attempted"
    )

    # Diagnostic fields
    fallback_reason: str | None = Field(
        default=None, description="Human-readable reason fallback was used"
    )
    security_challenge_detected: bool = Field(
        default=False, description="Whether WAF/captcha was detected"
    )
    attempts: list[ProductSearchAttempt] = Field(
        default_factory=list, description="Query attempts made during search"
    )

    # Actionable guidance
    search_url: str | None = Field(
        default=None, description="Direct URL to search results on heb.com"
    )
    playwright_fallback_available: bool = Field(
        default=False, description="Whether Playwright can be used as fallback"
    )
    playwright_instructions: list[str] | None = Field(
        default=None, description="Instructions for using Playwright MCP fallback"
    )

    # Session status fields (for proactive refresh guidance)
    session_needs_refresh: bool = Field(
        default=False, description="Whether session needs refresh before searching"
    )
    session_freshness: dict[str, Any] | None = Field(
        default=None, description="Session freshness details from check_session_freshness()"
    )
