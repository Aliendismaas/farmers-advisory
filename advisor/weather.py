"""Open-Meteo forecast fetch (no API key for non-commercial use)."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import requests
from django.conf import settings

from .models import WeatherDataSource

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_forecast(latitude: Decimal | float, longitude: Decimal | float) -> dict[str, Any] | None:
    source = WeatherDataSource.objects.filter(is_primary=True, is_active=True).first()
    endpoint = source.base_url if source else OPEN_METEO_URL
    params = {
        "latitude": float(latitude),
        "longitude": float(longitude),
        "current": "temperature_2m,relative_humidity_2m,precipitation,rain,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
        "forecast_days": 14,
        "timezone": "auto",
    }
    headers = {"User-Agent": settings.HTTP_USER_AGENT}
    try:
        resp = requests.get(endpoint, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.warning("Open-Meteo request failed: %s", exc)
        return None
