from __future__ import annotations

from datetime import date
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .forms import (
    AdvisoryRuleForm,
    BroadcastSmsForm,
    CropForm,
    LocationSearchForm,
    NotificationPreferenceForm,
    PhoneAuthenticationForm,
    ProfileSettingsForm,
    RegisterFarmerForm,
    SignUpForm,
    SmsPasswordResetRequestForm,
    SmsPasswordResetVerifyForm,
    WeatherDataSourceForm,
)
from .geocode import is_within_iringa, search_places
from .models import (
    AdminAuditLog,
    AdvisoryMessage,
    AdvisoryRule,
    Crop,
    FarmerCrop,
    FarmerProfile,
    GrowingZone,
    Notification,
    NotificationPreference,
    PasswordResetOTP,
    WeatherDataSource,
)
from .services import (
    build_and_store_advisory,
    current_temperature_line,
    get_or_refresh_weather,
    maybe_send_emergency_alert,
    recent_advisories_for_profile,
    send_sms_notification,
    send_welcome_sms,
    _sms_provider,
)


def admin_role_required(view_func):
    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args, **kwargs):
        profile, _ = FarmerProfile.objects.get_or_create(user=request.user)
        if not (request.user.is_superuser or profile.is_admin_role()):
            messages.error(request, "You are not allowed to access admin controls.")
            return redirect("advisor:dashboard")
        return view_func(request, *args, **kwargs)

    return login_required(_wrapped)


def register(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("advisor:dashboard")
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            profile, _ = FarmerProfile.objects.get_or_create(user=user)
            profile.phone = form.cleaned_data["phone_number"]
            profile.save(update_fields=["phone"])
            send_welcome_sms(profile, registered_by_admin=False)
            login(request, user)
            messages.success(request, "Welcome! Set your farm location next.")
            return redirect("advisor:onboarding")
    else:
        form = SignUpForm()
    return render(request, "advisor/register.html", {"form": form})


class AdvisorLoginView(LoginView):
    template_name = "advisor/login.html"
    authentication_form = PhoneAuthenticationForm
    redirect_authenticated_user = True


@login_required
@require_http_methods(["GET", "POST"])
def onboarding(request: HttpRequest) -> HttpResponse:
    profile, _ = FarmerProfile.objects.get_or_create(user=request.user)

    search_form = LocationSearchForm()
    geo_results = request.session.get("geo_results") or []

    if request.method == "POST":
        if "search" in request.POST:
            search_form = LocationSearchForm(request.POST)
            if search_form.is_valid():
                raw = search_places(search_form.cleaned_data["q"])
                geo_results = []
                for r in raw:
                    try:
                        geo_results.append(
                            {
                                "lat": str(r["lat"]),
                                "lon": str(r["lon"]),
                                "label": r.get("display_name", ""),
                            }
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
                request.session["geo_results"] = geo_results
                if not geo_results:
                    messages.warning(request, "No places found. Try different words.")

        if "pick_index" in request.POST:
            try:
                idx = int(request.POST.get("pick_index", ""))
            except ValueError:
                idx = -1
            stored = request.session.get("geo_results") or []
            if 0 <= idx < len(stored):
                choice = stored[idx]
                try:
                    lat = float(choice["lat"])
                    lon = float(choice["lon"])
                except (ValueError, TypeError):
                    messages.error(request, "Invalid location data. Please search again.")
                else:
                    if not is_within_iringa(lat, lon):
                        messages.error(
                            request,
                            "That location is outside Iringa Region. "
                            "Please search for a village or town within Iringa.",
                        )
                    else:
                        profile.latitude = choice["lat"]
                        profile.longitude = choice["lon"]
                        profile.location_label = choice.get("label", "")[:255]
                        profile.onboarding_complete = True
                        profile.save()
                        request.session.pop("geo_results", None)
                        messages.success(request, "Location saved.")
                        return redirect("advisor:dashboard")
            else:
                messages.error(request, "That result is no longer available; search again.")

    return render(
        request,
        "advisor/onboarding.html",
        {
            "search_form": search_form,
            "geo_results": geo_results,
        },
    )


def _require_profile_ready(request: HttpRequest) -> FarmerProfile | None:
    profile, _ = FarmerProfile.objects.get_or_create(user=request.user)
    if not profile.onboarding_complete or not profile.has_coordinates():
        return None
    return profile


def _time_greeting() -> str:
    from datetime import datetime
    hour = datetime.now().hour
    if hour < 12:
        return "Morning"
    if hour < 17:
        return "Afternoon"
    if hour < 21:
        return "Evening"
    return "Night"


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    profile, _ = FarmerProfile.objects.get_or_create(user=request.user)
    if request.user.is_staff or request.user.is_superuser or profile.is_admin_role():
        return redirect("advisor:admin_panel")

    if not profile.onboarding_complete or not profile.has_coordinates():
        return redirect("advisor:onboarding")

    pref, _ = NotificationPreference.objects.get_or_create(profile=profile)
    if pref.advisory_preference is None:
        return redirect("advisor:advisory_preference_setup")

    payload, wx_warn = get_or_refresh_weather(profile)
    today = date.today()

    rows = []
    for fc in FarmerCrop.objects.filter(profile=profile).select_related("crop", "crop__growing_zone"):
        c = fc.crop
        adv = build_and_store_advisory(
            profile=profile,
            crop=c,
            today=today,
            weather_payload=payload,
        )
        rows.append({"farmer_crop": fc, "advisory": adv})

    maybe_send_emergency_alert(profile, payload)
    adv_pref = pref.advisory_preference  # "planting", "harvest", or "both"
    return render(
        request,
        "advisor/dashboard.html",
        {
            "profile": profile,
            "weather_payload": payload,
            "weather_warning": wx_warn,
            "current_temp": current_temperature_line(payload),
            "rows": rows,
            "advisory_history": recent_advisories_for_profile(profile, limit=12),
            "notification_pref": pref,
            "advisory_preference": adv_pref,
            "greeting": _time_greeting(),
        },
    )


@login_required
def crop_library(request: HttpRequest) -> HttpResponse:
    profile = _require_profile_ready(request)
    if profile is None:
        return redirect("advisor:onboarding")

    crops = Crop.objects.select_related("growing_zone").all()
    tracked = set(
        FarmerCrop.objects.filter(profile=profile).values_list("crop_id", flat=True)
    )
    return render(
        request,
        "advisor/crop_library.html",
        {"crops": crops, "tracked": tracked},
    )


@login_required
def crop_detail(request: HttpRequest, slug: str) -> HttpResponse:
    profile = _require_profile_ready(request)
    if profile is None:
        return redirect("advisor:onboarding")

    crop = get_object_or_404(Crop.objects.select_related("growing_zone"), slug=slug)
    payload, wx_warn = get_or_refresh_weather(profile)
    today = date.today()
    adv = build_and_store_advisory(
        profile=profile,
        crop=crop,
        today=today,
        weather_payload=payload,
    )
    is_tracked = FarmerCrop.objects.filter(profile=profile, crop=crop).exists()
    crop_history = AdvisoryMessage.objects.filter(profile=profile, crop=crop)[:10]
    return render(
        request,
        "advisor/crop_detail.html",
        {
            "crop": crop,
            "advisory": adv,
            "is_tracked": is_tracked,
            "weather_warning": wx_warn,
            "current_temp": current_temperature_line(payload),
            "crop_history": crop_history,
        },
    )


@login_required
@require_http_methods(["POST"])
def crop_track(request: HttpRequest, slug: str) -> HttpResponse:
    profile = _require_profile_ready(request)
    if profile is None:
        return redirect("advisor:onboarding")
    crop = get_object_or_404(Crop, slug=slug)
    FarmerCrop.objects.get_or_create(profile=profile, crop=crop)
    messages.success(request, f"Added {crop.name} to your list.")
    return redirect("advisor:crop_detail", slug=crop.slug)


@login_required
@require_http_methods(["POST"])
def crop_untrack(request: HttpRequest, slug: str) -> HttpResponse:
    profile = _require_profile_ready(request)
    if profile is None:
        return redirect("advisor:onboarding")
    crop = get_object_or_404(Crop, slug=slug)
    FarmerCrop.objects.filter(profile=profile, crop=crop).delete()
    messages.info(request, f"Removed {crop.name} from your list.")
    return redirect("advisor:crop_detail", slug=crop.slug)


def home(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("advisor:dashboard")
    return render(request, "advisor/home.html")


@login_required
@require_http_methods(["GET", "POST"])
def notification_preferences(request: HttpRequest) -> HttpResponse:
    profile, _ = FarmerProfile.objects.get_or_create(user=request.user)
    pref, _ = NotificationPreference.objects.get_or_create(profile=profile)
    if request.method == "POST":
        form = NotificationPreferenceForm(request.POST, instance=pref)
        if form.is_valid():
            form.save()
            messages.success(request, "Notification preferences saved.")
            return redirect("advisor:notification_preferences")
    else:
        form = NotificationPreferenceForm(instance=pref)
    return render(request, "advisor/notification_preferences.html", {"form": form, "profile": profile})


@login_required
def notification_history(request: HttpRequest) -> HttpResponse:
    profile, _ = FarmerProfile.objects.get_or_create(user=request.user)
    notifications = Notification.objects.filter(profile=profile).order_by("-created_at")[:50]
    return render(
        request,
        "advisor/notification_history.html",
        {"notifications": notifications, "profile": profile},
    )


@login_required
@require_http_methods(["GET", "POST"])
def profile_settings(request: HttpRequest) -> HttpResponse:
    profile, _ = FarmerProfile.objects.get_or_create(user=request.user)
    user = request.user

    if request.method == "POST":
        form = ProfileSettingsForm(request.POST, user=user, profile=profile)
        if form.is_valid():
            new_phone = (form.cleaned_data.get("phone") or "").strip()

            if new_phone and new_phone != user.username:
                user.username = new_phone
                profile.phone = new_phone
                user.save()
                profile.save(update_fields=["phone"])
            messages.success(request, "Profile updated successfully.")
            return redirect("advisor:profile_settings")
    else:
        form = ProfileSettingsForm(user=user, profile=profile)

    return render(
        request,
        "advisor/profile_settings.html",
        {"form": form, "profile": profile},
    )


@admin_role_required
def admin_panel(request: HttpRequest) -> HttpResponse:
    total_users = FarmerProfile.objects.count()
    tracked_crops = FarmerCrop.objects.count()
    pending_notifications = Notification.objects.filter(status=Notification.Status.PENDING).count()
    recent_failures = Notification.objects.filter(status=Notification.Status.FAILED)[:10]
    recent_audits = AdminAuditLog.objects.select_related("actor")[:10]
    return render(
        request,
        "advisor/admin_panel.html",
        {
            "total_users": total_users,
            "tracked_crops": tracked_crops,
            "pending_notifications": pending_notifications,
            "recent_failures": recent_failures,
            "recent_audits": recent_audits,
            "weather_source_count": WeatherDataSource.objects.filter(is_active=True).count(),
        },
    )


@admin_role_required
@require_http_methods(["GET", "POST"])
def admin_users(request: HttpRequest) -> HttpResponse:
    profiles = FarmerProfile.objects.select_related("user").order_by("-id")
    if request.method == "POST":
        profile = get_object_or_404(FarmerProfile, id=request.POST.get("profile_id"))
        role = request.POST.get("role")
        if role in dict(FarmerProfile.UserRole.choices):
            profile.role = role
            profile.save(update_fields=["role"])
            profile.user.is_staff = role == FarmerProfile.UserRole.ADMIN
            profile.user.save(update_fields=["is_staff"])
            AdminAuditLog.objects.create(
                actor=request.user,
                action="update_user_role",
                target_type="FarmerProfile",
                target_id=str(profile.id),
                details=f"Role changed to {role}",
            )
            messages.success(request, f"Updated role for {profile.user.username}.")
        return redirect("advisor:admin_users")
    return render(
        request,
        "advisor/admin_users.html",
        {"profiles": profiles, "roles": FarmerProfile.UserRole.choices},
    )


@admin_role_required
@require_http_methods(["GET", "POST"])
def admin_rules(request: HttpRequest) -> HttpResponse:
    if request.method == "POST" and "delete_rule" in request.POST:
        rule_id = request.POST.get("delete_rule")
        rule = get_object_or_404(AdvisoryRule, id=rule_id)
        name = rule.name
        AdminAuditLog.objects.create(
            actor=request.user,
            action="delete_rule",
            target_type="AdvisoryRule",
            target_id=str(rule.id),
            details=f"Deleted rule: {rule.key}",
        )
        rule.delete()
        messages.success(request, f"Rule '{name}' deleted.")
        return redirect("advisor:admin_rules")

    form = AdvisoryRuleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        key = form.cleaned_data["key"]
        rule, created = AdvisoryRule.objects.update_or_create(
            key=key,
            defaults={
                "name": form.cleaned_data["name"],
                "value": form.cleaned_data["value"],
                "description": form.cleaned_data.get("description", ""),
                "is_active": form.cleaned_data["is_active"],
            },
        )
        AdminAuditLog.objects.create(
            actor=request.user,
            action="create_rule" if created else "update_rule",
            target_type="AdvisoryRule",
            target_id=str(rule.id),
            details=f"{rule.key}={rule.value}",
        )
        messages.success(request, f"Rule '{'created' if created else 'updated'}' successfully.")
        return redirect("advisor:admin_rules")

    rules = AdvisoryRule.objects.order_by("name")
    return render(request, "advisor/admin_rules.html", {"form": form, "rules": rules})


@admin_role_required
@require_http_methods(["GET", "POST"])
def admin_rule_edit(request: HttpRequest, rule_id: int) -> HttpResponse:
    rule = get_object_or_404(AdvisoryRule, id=rule_id)
    form = AdvisoryRuleForm(request.POST or None, instance=rule)
    if request.method == "POST" and form.is_valid():
        form.save()
        AdminAuditLog.objects.create(
            actor=request.user,
            action="edit_rule",
            target_type="AdvisoryRule",
            target_id=str(rule.id),
            details=f"{rule.key}={rule.value}",
        )
        messages.success(request, f"Rule '{rule.name}' updated.")
        return redirect("advisor:admin_rules")
    return render(
        request,
        "advisor/admin_rule_edit.html",
        {"form": form, "rule": rule},
    )


@admin_role_required
@require_http_methods(["POST"])
def admin_rule_delete(request: HttpRequest, rule_id: int) -> HttpResponse:
    rule = get_object_or_404(AdvisoryRule, id=rule_id)
    name = rule.name
    AdminAuditLog.objects.create(
        actor=request.user,
        action="delete_rule",
        target_type="AdvisoryRule",
        target_id=str(rule_id),
        details=f"Deleted rule: {rule.key}",
    )
    rule.delete()
    messages.success(request, f"Rule '{name}' deleted.")
    return redirect("advisor:admin_rules")


@admin_role_required
@require_http_methods(["GET", "POST"])
def admin_weather_sources(request: HttpRequest) -> HttpResponse:
    form = WeatherDataSourceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        source = form.save()
        AdminAuditLog.objects.create(
            actor=request.user,
            action="upsert_weather_source",
            target_type="WeatherDataSource",
            target_id=str(source.id),
            details=source.base_url,
        )
        messages.success(request, "Weather data source saved.")
        return redirect("advisor:admin_weather_sources")
    sources = WeatherDataSource.objects.order_by("name")
    return render(
        request,
        "advisor/admin_weather_sources.html",
        {"form": form, "sources": sources},
    )


@admin_role_required
def admin_advisory_history(request: HttpRequest) -> HttpResponse:
    advisory_history = AdvisoryMessage.objects.select_related("profile__user", "crop")[:100]
    return render(
        request,
        "advisor/admin_advisory_history.html",
        {"advisory_history": advisory_history},
    )


@admin_role_required
@require_http_methods(["GET", "POST"])
def admin_crops(request: HttpRequest) -> HttpResponse:
    if request.method == "POST" and "delete_crop" in request.POST:
        crop = get_object_or_404(Crop, id=request.POST.get("delete_crop"))
        name = crop.name
        AdminAuditLog.objects.create(
            actor=request.user,
            action="delete_crop",
            target_type="Crop",
            target_id=str(crop.id),
            details=f"Deleted crop: {name}",
        )
        crop.delete()
        messages.success(request, f"Crop '{name}' deleted.")
        return redirect("advisor:admin_crops")

    form = CropForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        from django.utils.text import slugify
        crop = form.save(commit=False)
        crop.slug = slugify(crop.name)[:120]
        crop.save()
        AdminAuditLog.objects.create(
            actor=request.user,
            action="create_crop",
            target_type="Crop",
            target_id=str(crop.id),
            details=f"Created crop: {crop.name}",
        )
        messages.success(request, f"Crop '{crop.name}' created.")
        return redirect("advisor:admin_crops")

    crops = Crop.objects.select_related("growing_zone").all()
    return render(request, "advisor/admin_crops.html", {"form": form, "crops": crops})


@admin_role_required
@require_http_methods(["GET", "POST"])
def admin_crop_edit(request: HttpRequest, crop_id: int) -> HttpResponse:
    crop = get_object_or_404(Crop, id=crop_id)
    form = CropForm(request.POST or None, request.FILES or None, instance=crop)
    if request.method == "POST" and form.is_valid():
        from django.utils.text import slugify
        updated = form.save(commit=False)
        updated.slug = slugify(updated.name)[:120]
        updated.save()
        AdminAuditLog.objects.create(
            actor=request.user,
            action="edit_crop",
            target_type="Crop",
            target_id=str(crop.id),
            details=f"Updated crop: {crop.name}",
        )
        messages.success(request, f"Crop '{crop.name}' updated.")
        return redirect("advisor:admin_crops")
    return render(request, "advisor/admin_crop_edit.html", {"form": form, "crop": crop})


@admin_role_required
@require_http_methods(["GET", "POST"])
def admin_register_farmer(request: HttpRequest) -> HttpResponse:
    from django.contrib.auth.models import User
    from django.utils.text import slugify as _slugify

    form = RegisterFarmerForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["phone"]
        full_name = form.cleaned_data["full_name"].strip()
        location_query = form.cleaned_data["location_query"]
        selected_crops = form.cleaned_data["crops"]

        # Geocode the location within Iringa Region
        from .geocode import search_places, is_within_iringa
        geo_hits = search_places(location_query, limit=3)
        location_label = ""
        lat = lon = None
        for hit in geo_hits:
            try:
                hit_lat = float(hit["lat"])
                hit_lon = float(hit["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if is_within_iringa(hit_lat, hit_lon):
                lat, lon = hit_lat, hit_lon
                location_label = hit.get("display_name", location_query)[:255]
                break

        if lat is None:
            form.add_error(
                "location_query",
                "Could not find that location within Iringa Region. "
                "Try a more specific village or town name.",
            )
        else:
            # Create the Django user (offline farmer — unusable password)
            first_name, _, last_name = full_name.partition(" ")
            user = User.objects.create_user(
                username=phone,
                first_name=first_name.strip(),
                last_name=last_name.strip(),
                password=None,
            )

            profile, _ = FarmerProfile.objects.update_or_create(
                user=user,
                defaults={
                    "phone": phone,
                    "latitude": lat,
                    "longitude": lon,
                    "location_label": location_label,
                    "onboarding_complete": True,
                    "role": FarmerProfile.UserRole.FARMER,
                },
            )

            for crop in selected_crops:
                FarmerCrop.objects.get_or_create(profile=profile, crop=crop)

            send_welcome_sms(profile, registered_by_admin=True)

            AdminAuditLog.objects.create(
                actor=request.user,
                action="register_farmer",
                target_type="FarmerProfile",
                target_id=str(profile.id),
                details=f"Registered offline farmer: {full_name} ({phone})",
            )

            messages.success(
                request,
                f"Farmer '{full_name}' registered successfully. "
                f"A welcome SMS has been sent to {phone}.",
            )
            return redirect("advisor:admin_register_farmer")

    return render(request, "advisor/admin_register_farmer.html", {"form": form})


@admin_role_required
@require_http_methods(["GET", "POST"])
def admin_broadcast_sms(request: HttpRequest) -> HttpResponse:
    from django.db.models import Count
    import json

    sms_enabled_ids = set(
        NotificationPreference.objects.filter(sms_enabled=True).values_list("profile_id", flat=True)
    )
    base_qs = FarmerCrop.objects.filter(
        profile__onboarding_complete=True,
        profile__phone__gt="",
        profile_id__in=sms_enabled_ids,
    )

    def _count_by_crop(qs):
        return {
            str(r["crop_id"]): r["n"]
            for r in qs.values("crop_id").annotate(n=Count("id"))
        }

    all_counts = _count_by_crop(base_qs)
    planting_counts = _count_by_crop(
        base_qs.filter(
            profile__notification_preference__advisory_preference__in=["planting", "both"]
        )
    )
    harvest_counts = _count_by_crop(
        base_qs.filter(
            profile__notification_preference__advisory_preference__in=["harvest", "both"]
        )
    )
    crop_recipient_counts = {
        cid: {
            "all": all_counts.get(cid, 0),
            "planting": planting_counts.get(cid, 0),
            "harvest": harvest_counts.get(cid, 0),
        }
        for cid in set(all_counts) | set(planting_counts) | set(harvest_counts)
    }

    form = BroadcastSmsForm(request.POST or None)
    results = None

    if request.method == "POST" and form.is_valid():
        crop = form.cleaned_data["crop"]
        message = form.cleaned_data["message"]
        advisory_type = form.cleaned_data["advisory_type"]

        eligible = FarmerCrop.objects.filter(
            crop=crop,
            profile__onboarding_complete=True,
            profile__phone__gt="",
            profile_id__in=sms_enabled_ids,
        )
        if advisory_type == "planting":
            eligible = eligible.filter(
                profile__notification_preference__advisory_preference__in=["planting", "both"]
            )
        elif advisory_type == "harvest":
            eligible = eligible.filter(
                profile__notification_preference__advisory_preference__in=["harvest", "both"]
            )
        eligible = eligible.select_related("profile__user", "profile")

        sent = 0
        failed = 0
        failed_details = []

        for fc in eligible:
            notif = send_sms_notification(
                profile=fc.profile,
                category=Notification.Category.ADVISORY,
                message=message,
            )
            if notif.status == Notification.Status.SENT:
                sent += 1
            else:
                failed += 1
                failed_details.append({
                    "username": fc.profile.user.username,
                    "error": notif.error_message or "Unknown error",
                })

        AdminAuditLog.objects.create(
            actor=request.user,
            action="broadcast_sms",
            target_type="Crop",
            target_id=str(crop.id),
            details=f"Broadcast to {crop.name} [{advisory_type}]: sent={sent}, failed={failed}. Message: {message[:80]}",
        )

        results = {
            "crop_name": crop.name,
            "advisory_type": advisory_type,
            "message": message,
            "sent": sent,
            "failed": failed,
            "failed_details": failed_details,
        }

    return render(request, "advisor/admin_broadcast_sms.html", {
        "form": form,
        "results": results,
        "crop_recipient_counts_json": json.dumps(crop_recipient_counts),
    })


@login_required
@require_http_methods(["GET", "POST"])
def advisory_preference_setup(request: HttpRequest) -> HttpResponse:
    profile, _ = FarmerProfile.objects.get_or_create(user=request.user)
    if not profile.onboarding_complete or not profile.has_coordinates():
        return redirect("advisor:onboarding")

    pref, _ = NotificationPreference.objects.get_or_create(profile=profile)

    if request.method == "POST":
        choice = request.POST.get("advisory_preference")
        valid = {c[0] for c in NotificationPreference.AdvisoryPreference.choices}
        if choice not in valid:
            messages.error(request, "Please select a valid advisory type.")
        else:
            pref.advisory_preference = choice
            pref.save(update_fields=["advisory_preference"])
            return redirect("advisor:dashboard")

    return render(request, "advisor/advisory_preference.html", {
        "AdvisoryPreference": NotificationPreference.AdvisoryPreference,
        "current": pref.advisory_preference,
    })


# ─── SMS Password Reset ────────────────────────────────────────────────────

import random
import string
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


def _generate_otp() -> str:
    return "".join(random.choices(string.digits, k=6))


@require_http_methods(["GET", "POST"])
def sms_password_reset_request(request: HttpRequest) -> HttpResponse:
    """Step 1: farmer enters phone → OTP sent via SMS."""
    if request.user.is_authenticated:
        return redirect("advisor:dashboard")

    form = SmsPasswordResetRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["phone"]

        # Rate-limit: max 3 OTPs per phone in the last hour
        recent_count = PasswordResetOTP.objects.filter(
            phone=phone,
            created_at__gte=timezone.now() - timedelta(hours=1),
        ).count()

        if recent_count < 3 and User.objects.filter(username=phone).exists():
            # Delete old unused OTPs for this phone
            PasswordResetOTP.objects.filter(phone=phone, is_used=False).delete()

            otp = PasswordResetOTP.objects.create(
                phone=phone,
                code=_generate_otp(),
                expires_at=timezone.now() + timedelta(minutes=10),
            )
            _sms_provider().send_sms(
                phone,
                f"Your FarmWise password reset code is: {otp.code}\n"
                "This code expires in 10 minutes. Do not share it with anyone.",
            )

        # Always show the same page — don't reveal if phone is registered
        request.session["reset_phone"] = phone
        return redirect("advisor:sms_password_reset_verify")

    return render(request, "advisor/sms_password_reset_request.html", {"form": form})


@require_http_methods(["GET", "POST"])
def sms_password_reset_verify(request: HttpRequest) -> HttpResponse:
    """Step 2: farmer enters OTP + new password."""
    if request.user.is_authenticated:
        return redirect("advisor:dashboard")

    phone = request.session.get("reset_phone")
    if not phone:
        return redirect("advisor:sms_password_reset_request")

    form = SmsPasswordResetVerifyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        code = form.cleaned_data["code"]
        new_password = form.cleaned_data["new_password1"]

        otp = (
            PasswordResetOTP.objects
            .filter(phone=phone, code=code, is_used=False)
            .order_by("-created_at")
            .first()
        )

        if otp and otp.is_valid():
            try:
                user = User.objects.get(username=phone)
                user.set_password(new_password)
                user.save(update_fields=["password"])
                otp.is_used = True
                otp.save(update_fields=["is_used"])
                del request.session["reset_phone"]
                return redirect("advisor:sms_password_reset_complete")
            except User.DoesNotExist:
                pass

        form.add_error("code", "The code is invalid or has expired. Please try again.")

    return render(request, "advisor/sms_password_reset_verify.html", {
        "form": form,
        "phone_hint": phone[-4:] if phone else "",
    })


def sms_password_reset_complete(request: HttpRequest) -> HttpResponse:
    return render(request, "advisor/password_reset_complete.html")
