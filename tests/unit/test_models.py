"""Tests for data models."""



def test_store_model_required_fields():
    """Store model should require essential fields."""
    from texas_grocery_mcp.models import Store

    store = Store(
        store_id="590",
        name="H-E-B Mueller",
        address="1801 E 51st St, Austin, TX 78723",
    )

    assert store.store_id == "590"
    assert store.name == "H-E-B Mueller"
    assert store.address == "1801 E 51st St, Austin, TX 78723"


def test_product_model_minimal_fields():
    """Product model should work with minimal fields."""
    from texas_grocery_mcp.models import Product

    product = Product(
        sku="123456",
        name="HEB Whole Milk",
        price=3.49,
        available=True,
    )

    assert product.sku == "123456"
    assert product.price == 3.49


def test_product_model_full_fields():
    """Product model should accept all optional fields."""
    from texas_grocery_mcp.models import Product

    product = Product(
        sku="123456",
        name="HEB Whole Milk",
        price=3.49,
        available=True,
        brand="H-E-B",
        size="1 gallon",
        price_per_unit="$3.49/gal",
        image_url="https://example.com/milk.jpg",
        aisle="5",
        section="Dairy",
        on_sale=True,
        original_price=4.29,
    )

    assert product.brand == "H-E-B"
    assert product.on_sale is True


def test_cart_item_calculates_subtotal():
    """CartItem should calculate subtotal from price and quantity."""
    from texas_grocery_mcp.models import CartItem

    item = CartItem(
        sku="123456",
        name="HEB Whole Milk",
        price=3.49,
        quantity=2,
    )

    assert item.subtotal == 6.98


def test_error_response_structure():
    """ErrorResponse should have proper structure."""
    from texas_grocery_mcp.models import ErrorResponse

    error = ErrorResponse(
        code="HEB_API_TIMEOUT",
        category="external",
        message="HEB API request timed out",
        retry_after_seconds=30,
        suggestions=["Try again in 30 seconds"],
    )

    assert error.error is True
    assert error.category == "external"
    assert error.retry_after_seconds == 30


def test_store_model_supports_curbside_default_true():
    """Store model should have supports_curbside field defaulting to True."""
    from texas_grocery_mcp.models import Store

    store = Store(
        store_id="737",
        name="The Heights H-E-B",
        address="2300 N. SHEPHERD DR., HOUSTON, TX 77008",
    )

    # Default should be True (most stores support curbside)
    assert store.supports_curbside is True


def test_store_model_supports_curbside_explicit_false():
    """Store model should accept explicit supports_curbside=False."""
    from texas_grocery_mcp.models import Store

    store = Store(
        store_id="718",
        name="South Flores Market H-E-B",
        address="516 S FLORES STREET, SAN ANTONIO, TX 78204",
        supports_curbside=False,
    )

    assert store.supports_curbside is False


def test_store_model_supports_delivery_field():
    """Store model should have supports_delivery field."""
    from texas_grocery_mcp.models import Store

    store = Store(
        store_id="737",
        name="The Heights H-E-B",
        address="2300 N. SHEPHERD DR., HOUSTON, TX 77008",
        supports_delivery=True,
    )

    assert store.supports_delivery is True


def test_store_model_supports_delivery_default_false():
    """Store model supports_delivery should default to False."""
    from texas_grocery_mcp.models import Store

    store = Store(
        store_id="737",
        name="The Heights H-E-B",
        address="2300 N. SHEPHERD DR., HOUSTON, TX 77008",
    )

    # Default should be False (not all stores support delivery)
    assert store.supports_delivery is False


# ============================================================================
# ProductDetails Model Tests
# ============================================================================


def test_product_details_minimal_fields():
    """ProductDetails should work with minimal required fields."""
    from texas_grocery_mcp.models import ProductDetails

    details = ProductDetails(
        product_id="127074",
        sku="4122071073",
        name="H-E-B Extra Virgin Olive Oil",
        price=7.01,
        available=True,
    )

    assert details.product_id == "127074"
    assert details.sku == "4122071073"
    assert details.name == "H-E-B Extra Virgin Olive Oil"
    assert details.price == 7.01
    assert details.available is True


def test_product_details_food_item():
    """ProductDetails should handle a typical food item with all fields."""
    from texas_grocery_mcp.models import ExtendedNutrition, NutrientInfo, ProductDetails

    nutrition = ExtendedNutrition(
        serving_size="1 Tbsp (15mL)",
        servings_per_container="about 34",
        calories="120",
        nutrients=[
            NutrientInfo(
                title="Total Fat",
                unit="14g",
                percentage="18%",
                font_modifier="BOLD",
                sub_items=[
                    NutrientInfo(title="Saturated Fat", unit="2g", percentage="10%"),
                    NutrientInfo(title="Trans Fat", unit="0g"),
                ],
            ),
        ],
        vitamins_and_minerals=[
            NutrientInfo(title="Vitamin D", unit="0mcg", percentage="0%"),
        ],
    )

    details = ProductDetails(
        product_id="127074",
        sku="4122071073",
        upc="041220710737",
        name="H-E-B Extra Virgin Olive Oil",
        description="Also referred to as EVOO...",
        brand="H-E-B",
        is_own_brand=True,
        price=7.01,
        price_online=6.68,
        available=True,
        price_per_unit="$0.41 / fl oz",
        size="17 oz",
        ingredients="Extra Virgin Olive Oil.",
        safety_warning="WARNING: Overheating any oil can cause fire...",
        instructions="Store in a cool, dark place.",
        dietary_attributes=["Gluten free verified", "Made in Italy"],
        nutrition=nutrition,
        category_path=["Shop", "Pantry", "Oils"],
        location="Aisle 5",
        store_id=465,
        is_snap_eligible=True,
    )

    assert details.brand == "H-E-B"
    assert details.is_own_brand is True
    assert details.ingredients == "Extra Virgin Olive Oil."
    assert details.nutrition is not None
    assert details.nutrition.calories == "120"
    assert len(details.nutrition.nutrients) == 1
    assert details.nutrition.nutrients[0].title == "Total Fat"
    assert len(details.nutrition.nutrients[0].sub_items) == 2
    assert details.dietary_attributes == ["Gluten free verified", "Made in Italy"]
    assert details.is_snap_eligible is True


def test_product_details_produce_item():
    """ProductDetails should handle produce without nutrition facts."""
    from texas_grocery_mcp.models import ProductDetails

    details = ProductDetails(
        product_id="320228",
        sku="94011",
        name="Fresh Bunch of Organic Bananas",
        price=1.89,
        available=True,
        brand="Fresh",
        is_own_brand=False,
        size="Avg. 2.425 lbs",
        ingredients="Organic Bananas.",
        dietary_attributes=["Vegan", "Organic", "Low sodium"],
        category_path=["Shop", "Fruit & vegetables", "Bananas"],
        location="In Produce",
        nutrition=None,  # Produce typically has no nutrition panel
    )

    assert details.nutrition is None
    assert details.ingredients == "Organic Bananas."
    assert "Organic" in details.dietary_attributes
    assert details.location == "In Produce"


def test_product_details_non_food_item():
    """ProductDetails should handle non-food with warnings but no nutrition."""
    from texas_grocery_mcp.models import ProductDetails

    details = ProductDetails(
        product_id="1904127",
        sku="4460030112",
        name="Clorox Disinfecting Wipes",
        price=7.64,
        available=True,
        brand="Clorox",
        is_own_brand=False,
        size="3 pk",
        ingredients="n-Alkyl (C14, 60%...) Dimethyl Benzyl Ammonium Chloride: 0.184%...",
        safety_warning="PRECAUTIONARY STATEMENTS: HAZARDS TO HUMAN AND DOMESTIC ANIMALS...",
        instructions="Directions for Use: To clean and remove allergens...",
        dietary_attributes=[],  # Non-food has no dietary attributes
        nutrition=None,
        category_path=["Shop", "Everyday essentials", "Cleaners"],
        location="Aisle 11",
    )

    assert details.nutrition is None
    assert details.safety_warning is not None
    assert details.instructions is not None
    assert len(details.dietary_attributes) == 0


def test_nutrient_info_with_nested_sub_items():
    """NutrientInfo should handle nested sub_items correctly."""
    from texas_grocery_mcp.models import NutrientInfo

    nutrient = NutrientInfo(
        title="Total Carbohydrate",
        unit="0g",
        percentage="0%",
        font_modifier="BOLD",
        sub_items=[
            NutrientInfo(
                title="Dietary Fiber",
                unit="0g",
                percentage="0%",
            ),
            NutrientInfo(
                title="Total Sugars",
                unit="0g",
                sub_items=[
                    NutrientInfo(
                        title="Includes Added Sugars",
                        unit="0g",
                        percentage="0%",
                    ),
                ],
            ),
        ],
    )

    assert nutrient.title == "Total Carbohydrate"
    assert len(nutrient.sub_items) == 2
    assert nutrient.sub_items[0].title == "Dietary Fiber"
    assert nutrient.sub_items[1].title == "Total Sugars"
    assert len(nutrient.sub_items[1].sub_items) == 1
    assert nutrient.sub_items[1].sub_items[0].title == "Includes Added Sugars"
