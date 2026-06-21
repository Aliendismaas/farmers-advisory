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


CROP_TRANSLATIONS = {
    "en": {
        "cassava": "cassava",
        "common beans": "common beans",
        "cotton": "cotton",
        "dry beans": "dry beans",
        "groundnuts (peanuts)": "groundnuts",
        "irish potatoes": "Irish potatoes",
        "maize (vuli season)": "maize (Vuli season)",
        "maize (grain)": "maize",
        "onions": "onions",
        "paddy rice": "paddy rice",
        "potatoes": "potatoes",
        "sesame (simsim)": "sesame",
        "sorghum": "sorghum",
        "sunflower": "sunflower",
        "sweet potatoes": "sweet potatoes",
        "tomatoes": "tomatoes",
    },
    "sw": {
        "cassava": "muhogo",
        "common beans": "maharage ya kawaida",
        "cotton": "pamba",
        "dry beans": "maharage makavu",
        "groundnuts (peanuts)": "karanga",
        "irish potatoes": "viazi mviringo",
        "maize (vuli season)": "mahindi (msimu wa vuli)",
        "maize (grain)": "mahindi",
        "onions": "vitunguu",
        "paddy rice": "mpunga",
        "potatoes": "viazi",
        "sesame (simsim)": "ufuta",
        "sorghum": "mtama",
        "sunflower": "alizeti",
        "sweet potatoes": "viazi vitamu",
        "tomatoes": "nyanya",
    }
}


def _is_notable(advisory, adv_pref: str) -> bool:
    # Always process all crops to ensure out-of-season crop alerts are sent
    return True


def _already_sent_today(profile, crop) -> bool:
    today = timezone.now().date()
    return Notification.objects.filter(
        profile=profile,
        category=Notification.Category.ADVISORY,
        status=Notification.Status.SENT,
        created_at__date=today,
        message__contains=crop.name,
    ).exists()


def _build_sms_text(advisory, crop_name: str, adv_pref: str, lang: str) -> str:
    in_plant = advisory.planting_status in ("In season", "Marginal")
    in_harvest = advisory.harvest_status == "Harvest window"
    
    # Perform a case-insensitive lookup
    lookup_key = crop_name.strip().lower()
    crop_name_lower = CROP_TRANSLATIONS.get(lang, CROP_TRANSLATIONS["en"]).get(lookup_key, crop_name.lower())

    if lang == "sw":
        if adv_pref == "planting":
            if in_plant:
                msg = f"Ushauri: Huu ni msimu unaofaa wa kupanda {crop_name_lower} katika eneo lako. Kutokana na uwezekano wa mvua za kutosha katika siku zijazo, andaa shamba na anza upandaji kwa kutumia mbegu bora zinazopendekezwa."
            else:
                msg = f"Tahadhari: Kwa mujibu wa kalenda ya kilimo na hali ya hewa ya sasa, huu si msimu unaofaa wa kupanda {crop_name_lower} katika eneo lako. Inashauriwa kusubiri msimu rasmi wa upandaji kabla ya kuanza shughuli za kupanda ili kuepuka hasara za uzalishaji."
        elif adv_pref == "harvest":
            if in_harvest:
                msg = f"Ushauri: Huu ni msimu unaofaa wa kuvuna {crop_name_lower} katika eneo lako. Andaa shughuli za uvunaji na uhifadhi bora wa mazao ili kuepuka hasara baada ya mavuno."
            else:
                msg = f"Tahadhari: Kwa sasa zao la {crop_name_lower} halipo katika kipindi cha kuvuna kwa mujibu wa msimu wa kilimo wa eneo hili. Endelea kufuatilia maendeleo ya zao na ushauri wa kilimo mpaka kipindi cha mavuno kitakapofika."
        else:  # "both"
            if in_plant:
                msg = f"Ushauri: Huu ni msimu unaofaa wa kupanda {crop_name_lower} katika eneo lako. Kutokana na uwezekano wa mvua za kutosha katika siku zijazo, andaa shamba na anza upandaji kwa kutumia mbegu bora zinazopendekezwa."
            elif in_harvest:
                msg = f"Ushauri: Huu ni msimu unaofaa wa kuvuna {crop_name_lower} katika eneo lako. Andaa shughuli za uvunaji na uhifadhi bora wa mazao ili kuepuka hasara baada ya mavuno."
            else:
                msg = f"Hakuna ushauri wa kilimo unaoweza kutolewa kwa zao la {crop_name_lower} kwa sasa kwa sababu halipo ndani ya msimu wa kupanda wala kuvuna katika eneo hili. Tafadhali subiri msimu husika au chagua zao lingine linalostahimili hali ya sasa."
    else:  # "en" or other
        if adv_pref == "planting":
            if in_plant:
                msg = f"Advice: This is the suitable season for planting {crop_name_lower} in your area. Due to the likelihood of sufficient rain in the coming days, prepare the field and start planting using recommended quality seeds."
            else:
                msg = f"Warning: According to the agricultural calendar and current weather, this is not the suitable season for planting {crop_name_lower} in your area. It is advised to wait for the official planting season before starting planting activities to avoid production losses."
        elif adv_pref == "harvest":
            if in_harvest:
                msg = f"Advice: This is the suitable season for harvesting {crop_name_lower} in your area. Prepare harvesting and post-harvest storage activities to avoid post-harvest losses."
            else:
                msg = f"Warning: Currently, the {crop_name_lower} crop is not in the harvesting period according to the agricultural season of this area. Continue monitoring the crop development and agricultural advice until the harvest period arrives."
        else:  # "both"
            if in_plant:
                msg = f"Advice: This is the suitable season for planting {crop_name_lower} in your area. Due to the likelihood of sufficient rain in the coming days, prepare the field and start planting using recommended quality seeds."
            elif in_harvest:
                msg = f"Advice: This is the suitable season for harvesting {crop_name_lower} in your area. Prepare harvesting and post-harvest storage activities to avoid post-harvest losses."
            else:
                msg = f"No agricultural advice can be provided for {crop_name_lower} at this time because it is not within the planting or harvesting season in this area. Please wait for the relevant season or choose another crop that tolerates the current conditions."

    # Append weather warning notes if present and not the default "no flags" note
    notes = (advisory.weather_notes or "").strip()
    if notes and "No major weather red flags" not in notes:
        msg += " " + notes

    return msg[:459]


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

                message = _build_sms_text(sms_advisory, crop.name, adv_pref, lang)
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
