"""Forward geocoding via Nominatim (OSM). Results are restricted to Iringa Region, Tanzania."""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"

# Bounding box for Iringa Region, Tanzania
# viewbox format expected by Nominatim: left,top,right,bottom (west,north,east,south)
_IRINGA_SOUTH = -10.2
_IRINGA_NORTH = -7.0
_IRINGA_WEST = 34.5
_IRINGA_EAST = 36.8
_VIEWBOX = f"{_IRINGA_WEST},{_IRINGA_NORTH},{_IRINGA_EAST},{_IRINGA_SOUTH}"


def is_within_iringa(lat: float, lon: float) -> bool:
    """Return True if the coordinate falls inside Iringa Region's bounding box."""
    return (
        _IRINGA_SOUTH <= lat <= _IRINGA_NORTH
        and _IRINGA_WEST <= lon <= _IRINGA_EAST
    )


def search_places(query: str, limit: int = 5) -> list[dict[str, Any]]:
    if not query or not query.strip():
        return []
    q = query.strip()
    # Append region context so Nominatim prioritises Iringa results
    if "iringa" not in q.lower() and "tanzania" not in q.lower():
        q = f"{q}, Iringa, Tanzania"
    params = {
        "q": q,
        "format": "json",
        "limit": limit,
        "addressdetails": 0,
        "countrycodes": "tz",
        "viewbox": _VIEWBOX,
        "bounded": 1,
    }
    headers = {"User-Agent": settings.HTTP_USER_AGENT}
    try:
        resp = requests.get(NOMINATIM_SEARCH, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            return []
        # Secondary filter: discard anything that slipped outside the bounding box
        results = []
        for r in data:
            try:
                if is_within_iringa(float(r["lat"]), float(r["lon"])):
                    results.append(r)
            except (KeyError, TypeError, ValueError):
                continue
        return results
    except requests.RequestException as exc:
        logger.warning("Nominatim request failed: %s", exc)
        return []
