"""Rule-based planting / harvest guidance from crop calendars and forecast JSON."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.utils.translation import gettext as _


def month_in_planting_window(month: int, start: int, end: int) -> bool:
    """Inclusive month range; supports wrap (e.g. Oct–Mar)."""
    if 1 <= start <= 12 and 1 <= end <= 12 and 1 <= month <= 12:
        pass
    else:
        return False
    if start <= end:
        return start <= month <= end
    return month >= start or month <= end


def month_in_harvest_window(month: int, start: int, end: int) -> bool:
    return month_in_planting_window(month, start, end)


@dataclass
class WeatherFlags:
    frost_risk_days: int
    heat_stress_days: int
    heavy_rain_days: int
    max_daily_precip_mm: float


def analyze_forecast_payload(
    payload: dict[str, Any] | None,
    *,
    min_temp_c: int | None,
    max_temp_c: int | None,
    rain_sensitive: bool,
) -> WeatherFlags:
    if not payload or "daily" not in payload:
        return WeatherFlags(0, 0, 0, 0.0)

    daily = payload["daily"] or {}
    mins = daily.get("temperature_2m_min") or []
    maxs = daily.get("temperature_2m_max") or []
    precips = daily.get("precipitation_sum") or []

    frost_limit = min_temp_c if min_temp_c is not None else 2
    heat_limit = max_temp_c if max_temp_c is not None else 38

    frost_days = 0
    heat_days = 0
    heavy_days = 0
    max_precip = 0.0

    n = max(len(mins), len(maxs), len(precips))
    for i in range(n):
        lo = mins[i] if i < len(mins) else None
        hi = maxs[i] if i < len(maxs) else None
        pr = precips[i] if i < len(precips) else None
        if lo is not None and float(lo) < 2:
            frost_days += 1
        if hi is not None and float(hi) >= float(heat_limit):
            heat_days += 1
        if pr is not None:
            p = float(pr)
            max_precip = max(max_precip, p)
            if rain_sensitive and p >= 25:
                heavy_days += 1

    return WeatherFlags(frost_days, heat_days, heavy_days, max_precip)


@dataclass
class CropAdvisory:
    crop_name: str
    planting_status: str
    planting_detail: str
    harvest_status: str
    harvest_detail: str
    weather_notes: str


def advise_crop(
    *,
    crop_name: str,
    plant_start: int,
    plant_end: int,
    harvest_start: int,
    harvest_end: int,
    min_temp_c: int | None,
    max_temp_c: int | None,
    rain_sensitive: bool,
    today: date,
    forecast_payload: dict[str, Any] | None,
) -> CropAdvisory:
    m = today.month
    in_plant = month_in_planting_window(m, plant_start, plant_end)
    in_harvest = month_in_harvest_window(m, harvest_start, harvest_end)

    flags = analyze_forecast_payload(
        forecast_payload,
        min_temp_c=min_temp_c,
        max_temp_c=max_temp_c,
        rain_sensitive=rain_sensitive,
    )

    if in_plant:
        planting_status = "In season"
        planting_detail = _("This month falls within the typical planting window for your zone.")
    else:
        planting_status = "Outside window"
        planting_detail = _(
            "Typical planting months for this crop in your zone do not include "
            "the current month (%(month)s). Check again closer to the season."
        ) % {"month": today.strftime("%B")}

    if in_harvest:
        harvest_status = "Harvest window"
        harvest_detail = _("This month is within the typical harvest period for this crop in your zone.")
    else:
        harvest_status = "Not peak harvest"
        harvest_detail = _(
            "Peak harvest months for this crop differ from the current month; "
            "this is a general calendar guide only."
        )

    notes: list[str] = []
    if flags.frost_risk_days:
        notes.append(
            _("Next ~14 days include %(days)s day(s) with cold lows (frost risk possible); delay sensitive planting if unsure.")
            % {"days": flags.frost_risk_days}
        )
    if flags.heat_stress_days:
        notes.append(
            _("%(days)s hot day(s) forecast; ensure irrigation if planting or flowering.")
            % {"days": flags.heat_stress_days}
        )
    if flags.heavy_rain_days and rain_sensitive:
        notes.append(
            _("Heavy rain possible on %(days)s day(s); consider soil drainage before planting.")
            % {"days": flags.heavy_rain_days}
        )
    if not notes:
        notes.append("No major weather red flags in the next two-week outlook.")

    if in_plant and flags.frost_risk_days >= 3:
        planting_status = "Marginal"
        planting_detail += " " + _("Weather outlook shows repeated cold nights; treat as marginal.")

    if in_plant and flags.heat_stress_days >= 5:
        planting_status = "Marginal"
        planting_detail += " " + _("Sustained heat in the forecast; irrigate and avoid heat-stress windows if possible.")

    weather_notes = " ".join(notes)
    return CropAdvisory(
        crop_name=crop_name,
        planting_status=planting_status,
        planting_detail=planting_detail,
        harvest_status=harvest_status,
        harvest_detail=harvest_detail,
        weather_notes=weather_notes,
    )
