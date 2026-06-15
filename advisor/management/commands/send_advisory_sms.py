"""
Send advisory SMS to farmers when something notable is happening for their crops.

Notable conditions depend on the farmer's advisory_preference:
  - planting: planting window open ("In season"/"Marginal") or weather warning
  - harvest:  harvest window open ("Harvest window") or weather warning
  - both:     any of the above

At most one SMS per farmer per crop per calendar day.

Run daily (e.g. via cron or a scheduler):
    python manage.py send_advisory_sms
"""

from datetime import date

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.translation import activate, gettext as _

from advisor.advisory import advise_crop
from advisor.models import FarmerCrop, FarmerProfile, Notification, NotificationPreference
from advisor.services import build_and_store_advisory, get_or_refresh_weather, send_sms_notification


_NOTABLE_PLANTING = {"In season", "Marginal"}
_WEATHER_KEYWORDS = ("frost risk", "heavy rain", "hot day", "heat stress")


def _is_notable(advisory, adv_pref: str) -> bool:
    notes_lower = (advisory.weather_notes or "").lower()
    weather_hit = any(kw in notes_lower for kw in _WEATHER_KEYWORDS)

    if adv_pref == "planting":
        return advisory.planting_status in _NOTABLE_PLANTING or weather_hit
    if adv_pref == "harvest":
        return advisory.harvest_status == "Harvest window" or weather_hit
    # "both" or unset
    if advisory.planting_status in _NOTABLE_PLANTING:
        return True
    if advisory.harvest_status == "Harvest window":
        return True
    return weather_hit


def _already_sent_today(profile, crop) -> bool:
    today = timezone.now().date()
    return Notification.objects.filter(
        profile=profile,
        category=Notification.Category.ADVISORY,
        status=Notification.Status.SENT,
        created_at__date=today,
        message__contains=crop.name,
    ).exists()


def _build_sms_text(advisory, crop_name: str, adv_pref: str) -> str:
    recommendation_parts = []

    if adv_pref != "harvest" and advisory.planting_status in _NOTABLE_PLANTING:
        recommendation_parts.append(advisory.planting_detail)

    if adv_pref != "planting" and advisory.harvest_status == "Harvest window":
        recommendation_parts.append(advisory.harvest_detail)

    notes = (advisory.weather_notes or "").strip()
    if notes and "No major weather red flags" not in notes:
        recommendation_parts.append(notes)

    recommendation = " ".join(recommendation_parts) or advisory.planting_detail or advisory.harvest_detail or ""

    return f"{_('Crop')}: {crop_name}\n{_('Recommendation')}: {recommendation}"[:459]


class Command(BaseCommand):
    help = "Send advisory SMS to farmers when something notable is happening for their crops."

    def add_arguments(self, parser):
        parser.add_argument(
            "--test-sms",
            metavar="PHONE",
            help="Send a test SMS to this number and exit (e.g. 255712345678).",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print skip reasons.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Bypass the once-per-day guard and resend to all eligible farmers (useful for demos).",
        )

    def handle(self, *args, **options):
        if options.get("test_sms"):
            from advisor.services import _sms_provider
            phone = options["test_sms"]
            ok, result = _sms_provider().send_sms(phone, "FarmWise test SMS — if you see this, the API is working.")
            if ok:
                self.stdout.write(self.style.SUCCESS(f"Test SMS sent OK. Provider ID: {result}"))
            else:
                self.stderr.write(f"Test SMS FAILED: {result}")
            return

        # Advisory text must be in English so keyword comparisons work correctly.
        activate("en")

        today = date.today()
        sent = 0
        skipped = 0
        errors = 0
        force = options.get("force", False)
        verbose = options.get("verbose", False)

        sms_profiles = FarmerProfile.objects.filter(
            onboarding_complete=True,
            phone__gt="",
            latitude__isnull=False,
        ).select_related("user")

        for profile in sms_profiles:
            pref = NotificationPreference.objects.filter(profile=profile).first()
            if not pref or not pref.sms_enabled:
                if verbose:
                    self.stdout.write(f"  Skip {profile.user.username}: SMS not enabled")
                continue

            adv_pref = pref.advisory_preference or "both"

            payload, _ = get_or_refresh_weather(profile)

            farmer_crops = FarmerCrop.objects.filter(profile=profile).select_related("crop")
            for fc in farmer_crops:
                crop = fc.crop
                try:
                    advisory = build_and_store_advisory(
                        profile=profile,
                        crop=crop,
                        today=today,
                        weather_payload=payload,
                    )
                except Exception as exc:
                    self.stderr.write(f"  Advisory error for {profile} / {crop}: {exc}")
                    errors += 1
                    continue

                if not _is_notable(advisory, adv_pref):
                    if verbose:
                        self.stdout.write(
                            f"  Skip {profile.user.username}/{crop.name}: "
                            f"planting={advisory.planting_status}, harvest={advisory.harvest_status} "
                            f"(pref={adv_pref})"
                        )
                    skipped += 1
                    continue

                if not force and _already_sent_today(profile, crop):
                    if verbose:
                        self.stdout.write(f"  Skip {profile.user.username}/{crop.name}: already sent today")
                    skipped += 1
                    continue

                lang = pref.language or "en"
                if lang == "sw":
                    activate("sw")
                    sms_advisory = advise_crop(
                        crop_name=crop.name,
                        plant_start=crop.plant_start_month,
                        plant_end=crop.plant_end_month,
                        harvest_start=crop.harvest_start_month,
                        harvest_end=crop.harvest_end_month,
                        min_temp_c=crop.min_temp_c,
                        max_temp_c=crop.max_temp_c,
                        rain_sensitive=crop.rain_sensitive,
                        today=today,
                        forecast_payload=payload,
                    )
                else:
                    sms_advisory = advisory

                message = _build_sms_text(sms_advisory, crop.name, adv_pref)
                activate("en")
                notif = send_sms_notification(
                    profile=profile,
                    category=Notification.Category.ADVISORY,
                    message=message,
                )
                if notif.status == Notification.Status.SENT:
                    sent += 1
                    self.stdout.write(f"  Sent: {profile.user.username} / {crop.name}")
                else:
                    errors += 1
                    self.stderr.write(
                        f"  Failed: {profile.user.username} / {crop.name} — {notif.error_message}"
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Sent={sent}, Skipped={skipped}, Errors={errors}."
            )
        )
