"""Orchestration: weather cache, advisory generation, and notification dispatch."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import requests as http_requests
from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone

from .advisory import CropAdvisory, advise_crop
from .models import (
    AdvisoryMessage,
    AdvisoryRule,
    Crop,
    FarmerProfile,
    Notification,
    NotificationPreference,
    WeatherSnapshot,
)
from .weather import fetch_forecast

logger = logging.getLogger(__name__)


def get_or_refresh_weather(
    profile: FarmerProfile,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return (payload, warning_message).

    warning_message is non-None when the API fails but stale cache exists.
    """
    if not profile.has_coordinates():
        return None, "Add your farm location to see weather-based guidance."

    snap = WeatherSnapshot.objects.filter(profile=profile).first()
    ttl = getattr(settings, "WEATHER_CACHE_TTL_SECONDS", 1800)

    if snap:
        age = (timezone.now() - snap.fetched_at).total_seconds()
        if age < ttl and snap.payload:
            return snap.payload, None

    data = fetch_forecast(profile.latitude, profile.longitude)
    if data is None:
        if snap and snap.payload:
            return snap.payload, "Live weather is unavailable; showing the last saved forecast."
        return None, "Live weather is unavailable. Try again later."

    WeatherSnapshot.objects.update_or_create(
        profile=profile,
        defaults={
            "latitude": profile.latitude,
            "longitude": profile.longitude,
            "payload": data,
        },
    )
    return data, None


def _severity_from_advisory(advisory: CropAdvisory) -> str:
    notes = (advisory.weather_notes or "").lower()
    if "frost risk" in notes and "heavy rain" in notes:
        return AdvisoryMessage.Severity.WARNING
    if "frost risk" in notes or "heavy rain" in notes:
        return AdvisoryMessage.Severity.WARNING
    return AdvisoryMessage.Severity.INFO


def build_and_store_advisory(
    *,
    profile: FarmerProfile,
    crop: Crop,
    today,
    weather_payload: dict[str, Any] | None,
) -> CropAdvisory:
    """Generate a crop advisory and persist it — at most once per crop per day."""
    advisory = advise_crop(
        crop_name=crop.name,
        plant_start=crop.plant_start_month,
        plant_end=crop.plant_end_month,
        harvest_start=crop.harvest_start_month,
        harvest_end=crop.harvest_end_month,
        min_temp_c=crop.min_temp_c,
        max_temp_c=crop.max_temp_c,
        rain_sensitive=crop.rain_sensitive,
        today=today,
        forecast_payload=weather_payload,
    )

    already_stored = AdvisoryMessage.objects.filter(
        profile=profile,
        crop=crop,
        generated_at__date=today,
    ).exists()

    if not already_stored:
        AdvisoryMessage.objects.create(
            profile=profile,
            crop=crop,
            planting_status=advisory.planting_status,
            planting_detail=advisory.planting_detail,
            harvest_status=advisory.harvest_status,
            harvest_detail=advisory.harvest_detail,
            weather_notes=advisory.weather_notes,
            severity=_severity_from_advisory(advisory),
            weather_payload=weather_payload or {},
            location_label_snapshot=profile.location_label,
        )

    return advisory


def recent_advisories_for_profile(
    profile: FarmerProfile,
    *,
    limit: int = 20,
) -> QuerySet[AdvisoryMessage]:
    return AdvisoryMessage.objects.filter(profile=profile).select_related("crop")[:limit]


def refresh_weather_for_active_profiles(*, max_profiles: int | None = None) -> dict[str, int]:
    qs = FarmerProfile.objects.filter(
        onboarding_complete=True,
        latitude__isnull=False,
        longitude__isnull=False,
    ).order_by("id")
    if max_profiles:
        qs = qs[:max_profiles]

    refreshed = 0
    failed = 0
    for profile in qs:
        payload, warning = get_or_refresh_weather(profile)
        if payload:
            refreshed += 1
        else:
            failed += 1
            logger.warning("Weather refresh failed for profile %s: %s", profile.id, warning)
    return {"refreshed": refreshed, "failed": failed}


class SmsProviderAdapter(ABC):
    @abstractmethod
    def send_sms(self, to_number: str, message: str) -> tuple[bool, str]: ...


class ConsoleSmsProvider(SmsProviderAdapter):
    def send_sms(self, to_number: str, message: str) -> tuple[bool, str]:
        logger.info("SMS to %s: %s", to_number, message)
        return True, "console"


def _normalize_tz_phone(phone: str) -> str:
    """Normalize Tanzania number to international format: 255XXXXXXXXX."""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 12 and digits.startswith("255"):
        return digits
    if len(digits) == 10 and digits.startswith("0"):
        return "255" + digits[1:]
    if len(digits) == 9 and digits[0] in ("6", "7"):
        return "255" + digits
    return digits


class SewmrSmsProvider(SmsProviderAdapter):
    """Live SMS via api.sewmrsms.co.tz (Bearer token, REST/JSON)."""

    def send_sms(self, to_number: str, message: str) -> tuple[bool, str]:
        api_key = getattr(settings, "SEWMR_API_KEY", "")
        base_url = getattr(settings, "SEWMR_BASE_URL", "https://api.sewmrsms.co.tz/api/v1")
        sender_id = getattr(settings, "SMS_SENDER_ID", "FarmWise")

        phone = _normalize_tz_phone(to_number)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "phone_number": phone,
            "sender_id": sender_id,
            "message": message,
        }
        try:
            resp = http_requests.post(
                f"{base_url}/sms/send",
                headers=headers,
                json=payload,
                timeout=10,
            )
            logger.debug("SewmrSMS status=%s body=%s", resp.status_code, resp.text[:300])
            try:
                body = resp.json()
            except Exception:
                body = {}
            if body.get("success"):
                gw = (body.get("data") or {}).get("sms_gateway_response") or {}
                msg_id = str(gw.get("message_id") or "sent")
                return True, msg_id
            err = body.get("message") or f"HTTP {resp.status_code}: {resp.text[:200]}"
            return False, err
        except Exception as exc:
            logger.error("SewmrSMS request failed: %s", exc)
            return False, str(exc)


def _sms_provider() -> SmsProviderAdapter:
    if getattr(settings, "SEWMR_API_KEY", ""):
        return SewmrSmsProvider()
    return ConsoleSmsProvider()


def send_sms_notification(
    *,
    profile: FarmerProfile,
    category: str,
    message: str,
) -> Notification:
    notification = Notification.objects.create(
        profile=profile,
        channel=Notification.Channel.SMS,
        category=category,
        message=message,
    )

    pref, _ = NotificationPreference.objects.get_or_create(profile=profile)
    if not pref.sms_enabled:
        notification.status = Notification.Status.FAILED
        notification.error_message = "SMS is disabled for this profile."
        notification.save(update_fields=["status", "error_message"])
        return notification
    if not profile.phone:
        notification.status = Notification.Status.FAILED
        notification.error_message = "No phone number configured."
        notification.save(update_fields=["status", "error_message"])
        return notification

    ok, provider_message_id = _sms_provider().send_sms(profile.phone, message)
    if ok:
        notification.status = Notification.Status.SENT
        notification.provider_message_id = provider_message_id
        notification.sent_at = timezone.now()
        notification.save(update_fields=["status", "provider_message_id", "sent_at"])
    else:
        notification.status = Notification.Status.FAILED
        notification.retry_count += 1
        notification.error_message = provider_message_id
        notification.save(update_fields=["status", "retry_count", "error_message"])
    return notification


def send_welcome_sms(profile: FarmerProfile, *, registered_by_admin: bool = False) -> None:
    """Send a one-time welcome SMS and auto-enable SMS for the profile."""
    if not profile.phone:
        return
    pref, _ = NotificationPreference.objects.get_or_create(profile=profile)
    if not pref.sms_enabled:
        pref.sms_enabled = True
        pref.save(update_fields=["sms_enabled"])
    if registered_by_admin:
        msg = (
            "Welcome to FarmWise! You have been registered by your local extension officer. "
            "You will receive crop advisory messages for Iringa Region."
        )
    else:
        msg = (
            "Welcome to FarmWise! Your account is set up. "
            "Complete your farm setup to start receiving crop advisories for Iringa Region."
        )
    send_sms_notification(profile=profile, category=Notification.Category.ADVISORY, message=msg)


def _active_rule_float(rule_key: str, default: float) -> float:
    rule = AdvisoryRule.objects.filter(key=rule_key, is_active=True).first()
    if not rule:
        return default
    try:
        return float(rule.value)
    except ValueError:
        return default


def maybe_send_emergency_alert(
    profile: FarmerProfile,
    payload: dict[str, Any] | None,
) -> Notification | None:
    """Send an emergency SMS alert — at most once per profile per calendar day."""
    if not payload:
        return None

    today = timezone.now().date()
    already_alerted = Notification.objects.filter(
        profile=profile,
        category=Notification.Category.EMERGENCY,
        created_at__date=today,
    ).exists()
    if already_alerted:
        return None

    daily = payload.get("daily") or {}
    rains = daily.get("precipitation_sum") or []
    max_rain = max((float(v) for v in rains), default=0.0)
    drought_threshold = _active_rule_float("drought_mm_threshold", 1.0)
    heavy_rain_threshold = _active_rule_float("heavy_rain_mm_threshold", 35.0)

    if max_rain <= drought_threshold:
        return send_sms_notification(
            profile=profile,
            category=Notification.Category.EMERGENCY,
            message="Emergency alert: very low rainfall expected. Consider drought mitigation planning.",
        )
    if max_rain >= heavy_rain_threshold:
        return send_sms_notification(
            profile=profile,
            category=Notification.Category.EMERGENCY,
            message="Emergency alert: heavy rainfall expected. Protect seed beds and improve drainage.",
        )
    return None


def current_temperature_line(payload: dict[str, Any] | None) -> str:
    if not payload or "current" not in payload:
        return "—"
    cur = payload["current"] or {}
    t = cur.get("temperature_2m")
    if t is None:
        return "—"
    return f"{float(t):.1f} °C"
