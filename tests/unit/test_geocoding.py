"""Tests for geocoding service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from texas_grocery_mcp.services.geocoding import (
    GeocodingResult,
    GeocodingService,
)


class TestGeocodingResult:
    """Tests for GeocodingResult dataclass."""

    def test_basic_creation(self):
        """GeocodingResult should store all fields."""
        result = GeocodingResult(
            latitude=29.7604,
            longitude=-95.3698,
            city="Houston",
            state="TX",
            postcode="77007",
            display_name="Rice Military, Houston, TX 77007, USA",
        )

        assert result.latitude == 29.7604
        assert result.longitude == -95.3698
        assert result.city == "Houston"
        assert result.state == "TX"
        assert result.postcode == "77007"
        assert "Rice Military" in result.display_name

    def test_query_variations_with_all_fields(self):
        """get_query_variations should return zip, city/state, and original."""
        result = GeocodingResult(
            latitude=29.7604,
            longitude=-95.3698,
            city="Houston",
            state="TX",
            postcode="77007",
            display_name="Rice Military, Houston, TX",
        )

        variations = result.get_query_variations("Rice Military")

        assert variations == ["77007", "Houston, TX", "Rice Military"]

    def test_query_variations_zip_with_extension(self):
        """get_query_variations should handle zip codes with extensions."""
        result = GeocodingResult(
            latitude=29.7604,
            longitude=-95.3698,
            city="Houston",
            state="TX",
            postcode="77007-1234",
            display_name="Houston, TX",
        )

        variations = result.get_query_variations("some address")

        # Should extract just 5-digit zip
        assert variations[0] == "77007"

    def test_query_variations_no_zip(self):
        """get_query_variations should work without zip code."""
        result = GeocodingResult(
            latitude=29.7604,
            longitude=-95.3698,
            city="Houston",
            state="TX",
            postcode=None,
            display_name="Houston, TX",
        )

        variations = result.get_query_variations("downtown Houston")

        assert variations == ["Houston, TX", "downtown Houston"]

    def test_query_variations_no_city(self):
        """get_query_variations should work without city."""
        result = GeocodingResult(
            latitude=29.7604,
            longitude=-95.3698,
            city=None,
            state="TX",
            postcode="77007",
            display_name="77007, TX",
        )

        variations = result.get_query_variations("77007")

        # Should have zip and original (which is same as zip)
        assert "77007" in variations
        assert len(variations) == 1  # Deduped

    def test_query_variations_dedupes_original(self):
        """get_query_variations should not duplicate original query."""
        result = GeocodingResult(
            latitude=29.7604,
            longitude=-95.3698,
            city="Houston",
            state="TX",
            postcode="77007",
            display_name="Houston, TX",
        )

        # If original matches city/state format
        variations = result.get_query_variations("Houston, TX")

        # Should not have duplicate
        assert variations.count("Houston, TX") == 1


class TestGeocodingService:
    """Tests for GeocodingService class."""

    def test_haversine_miles_same_point(self):
        """Haversine should return 0 for same point."""
        distance = GeocodingService.haversine_miles(29.76, -95.37, 29.76, -95.37)
        assert distance == 0.0

    def test_haversine_miles_known_distance(self):
        """Haversine should calculate correct distance."""
        # Houston downtown to The Heights HEB (~3.8 miles)
        distance = GeocodingService.haversine_miles(
            29.7604, -95.3698,  # Downtown Houston
            29.8028, -95.4103,  # Heights HEB
        )
        assert 3.5 < distance < 4.5  # Allow some tolerance

    def test_haversine_miles_longer_distance(self):
        """Haversine should work for longer distances."""
        # Houston to Austin (~146 miles)
        distance = GeocodingService.haversine_miles(
            29.7604, -95.3698,  # Houston
            30.2672, -97.7431,  # Austin
        )
        assert 140 < distance < 160

    @pytest.mark.asyncio
    async def test_geocode_empty_address(self):
        """geocode should return None for empty address."""
        service = GeocodingService()
        try:
            result = await service.geocode("")
            assert result is None

            result = await service.geocode("   ")
            assert result is None
        finally:
            await service.close()

    @pytest.mark.asyncio
    async def test_geocode_parses_nominatim_response(self):
        """geocode should parse Nominatim response correctly."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "lat": "29.7604",
                "lon": "-95.3698",
                "display_name": (
                    "Rice Military, Houston, Harris County, Texas, 77007, United States"
                ),
                "address": {
                    "neighbourhood": "Rice Military",
                    "city": "Houston",
                    "county": "Harris County",
                    "state": "Texas",
                    "postcode": "77007",
                    "country": "United States",
                },
            }
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("texas_grocery_mcp.services.geocoding.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            service = GeocodingService()
            result = await service.geocode("Rice Military, Houston")

            assert result is not None
            assert result.latitude == 29.7604
            assert result.longitude == -95.3698
            assert result.city == "Houston"
            assert result.state == "TX"  # Abbreviated
            assert result.postcode == "77007"

            await service.close()

    @pytest.mark.asyncio
    async def test_geocode_handles_no_results(self):
        """geocode should return None when no results found."""
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()

        with patch("texas_grocery_mcp.services.geocoding.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            service = GeocodingService()
            result = await service.geocode("nonexistent place xyz123")

            assert result is None

            await service.close()

    @pytest.mark.asyncio
    async def test_geocode_handles_timeout(self):
        """geocode should return None on timeout."""
        import httpx

        with patch("texas_grocery_mcp.services.geocoding.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            service = GeocodingService()
            result = await service.geocode("Houston, TX")

            assert result is None

            await service.close()

    @pytest.mark.asyncio
    async def test_geocode_handles_http_error(self):
        """geocode should return None on HTTP error."""
        import httpx

        with patch("texas_grocery_mcp.services.geocoding.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "error", request=MagicMock(), response=MagicMock()
                )
            )
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            service = GeocodingService()
            result = await service.geocode("Houston, TX")

            assert result is None

            await service.close()

    def test_abbreviate_state_full_name(self):
        """_abbreviate_state should convert full state name."""
        service = GeocodingService()

        assert service._abbreviate_state("Texas") == "TX"
        assert service._abbreviate_state("texas") == "TX"
        assert service._abbreviate_state("California") == "CA"

    def test_abbreviate_state_already_abbreviated(self):
        """_abbreviate_state should keep abbreviations."""
        service = GeocodingService()

        assert service._abbreviate_state("TX") == "TX"
        assert service._abbreviate_state("tx") == "TX"

    def test_abbreviate_state_unknown(self):
        """_abbreviate_state should return unknown states as-is."""
        service = GeocodingService()

        assert service._abbreviate_state("Unknown State") == "Unknown State"

    @pytest.mark.asyncio
    async def test_geocode_uses_town_when_no_city(self):
        """geocode should use town field when city is missing."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "lat": "30.0",
                "lon": "-95.0",
                "display_name": "Some Town, TX",
                "address": {
                    "town": "Small Town",
                    "state": "Texas",
                    "postcode": "77777",
                },
            }
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("texas_grocery_mcp.services.geocoding.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            service = GeocodingService()
            result = await service.geocode("Small Town, TX")

            assert result is not None
            assert result.city == "Small Town"

            await service.close()
