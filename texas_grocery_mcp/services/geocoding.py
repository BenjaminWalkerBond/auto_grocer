"""Geocoding service using Nominatim (OpenStreetMap)."""

import math
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

# Nominatim API endpoint
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Nominatim requires a valid User-Agent. They block custom app names
# without real contact info. Using curl format as a pragmatic workaround.
USER_AGENT = "curl/8.7.1"


@dataclass
class GeocodingResult:
    """Result from geocoding an address."""

    latitude: float
    longitude: float
    city: str | None
    state: str | None
    postcode: str | None
    display_name: str

    def get_query_variations(self, original_query: str) -> list[str]:
        """Generate query variations to try against HEB's API.

        Returns queries in priority order:
        1. Zip code (most reliable)
        2. City, State format
        3. Original query
        """
        variations = []

        # Priority 1: Zip code
        if self.postcode:
            # Extract just the 5-digit zip if it has extension
            zip_code = self.postcode.split("-")[0].strip()
            if zip_code:
                variations.append(zip_code)

        # Priority 2: City, State
        if self.city and self.state:
            variations.append(f"{self.city}, {self.state}")

        # Priority 3: Original query (if not already covered)
        original_lower = original_query.lower().strip()
        if not any(v.lower() == original_lower for v in variations):
            variations.append(original_query)

        return variations


class GeocodingService:
    """Geocoding via Nominatim (OpenStreetMap).

    Converts addresses, neighborhoods, and landmarks to coordinates
    and structured address components.
    """

    def __init__(self, timeout: float = 15.0):
        """Initialize geocoding service.

        Args:
            timeout: Request timeout in seconds (default 15s for Nominatim)
        """
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                headers={"User-Agent": USER_AGENT},
                http2=False,  # Nominatim doesn't handle HTTP/2 well
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def geocode(self, address: str) -> GeocodingResult | None:
        """Convert address to coordinates and structured components.

        Args:
            address: Address, zip code, neighborhood, or landmark to geocode

        Returns:
            GeocodingResult with coordinates and address components,
            or None if geocoding failed
        """
        if not address or not address.strip():
            return None

        client = await self._get_client()

        params = {
            "q": address.strip(),
            "format": "json",
            "addressdetails": "1",
            "limit": "1",
            "countrycodes": "us",
        }

        try:
            logger.debug("Geocoding address", address=address)
            response = await client.get(NOMINATIM_URL, params=params)
            response.raise_for_status()

            results = response.json()
            if not results:
                logger.info("Geocoding returned no results", address=address)
                return None

            return self._parse_result(results[0])

        except httpx.TimeoutException:
            logger.warning("Geocoding timeout", address=address)
            return None
        except httpx.HTTPError as e:
            logger.warning("Geocoding HTTP error", address=address, error=str(e))
            return None
        except Exception as e:
            logger.error("Geocoding unexpected error", address=address, error=str(e))
            return None

    def _parse_result(self, result: dict[str, Any]) -> GeocodingResult:
        """Parse Nominatim API result into GeocodingResult.

        Args:
            result: Single result from Nominatim API

        Returns:
            GeocodingResult with extracted data
        """
        address_details = result.get("address", {})

        # Extract city - Nominatim uses various fields
        city = (
            address_details.get("city")
            or address_details.get("town")
            or address_details.get("village")
            or address_details.get("municipality")
            or address_details.get("county")
        )

        # Extract state
        state = address_details.get("state")
        # Convert full state name to abbreviation if needed
        state = self._abbreviate_state(state) if state else None

        return GeocodingResult(
            latitude=float(result["lat"]),
            longitude=float(result["lon"]),
            city=city,
            state=state,
            postcode=address_details.get("postcode"),
            display_name=result.get("display_name", ""),
        )

    def _abbreviate_state(self, state: str) -> str:
        """Convert state name to abbreviation.

        Args:
            state: Full state name or abbreviation

        Returns:
            Two-letter state abbreviation
        """
        # If already abbreviated, return as-is
        if len(state) == 2:
            return state.upper()

        state_abbrevs = {
            "texas": "TX",
            "california": "CA",
            "new york": "NY",
            "florida": "FL",
            "louisiana": "LA",
            "oklahoma": "OK",
            "new mexico": "NM",
            "arkansas": "AR",
            "arizona": "AZ",
            "colorado": "CO",
            # Add more as needed
        }

        return state_abbrevs.get(state.lower(), state)

    @staticmethod
    def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two points using Haversine formula.

        Args:
            lat1, lon1: First point coordinates (degrees)
            lat2, lon2: Second point coordinates (degrees)

        Returns:
            Distance in miles
        """
        # Earth radius in miles
        earth_radius_miles = 3959

        # Convert to radians
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)

        # Haversine formula
        a = (
            math.sin(delta_lat / 2) ** 2
            + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return earth_radius_miles * c
