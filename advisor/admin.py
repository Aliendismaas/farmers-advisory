from django.contrib import admin

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
    WeatherDataSource,
    WeatherSnapshot,
)


@admin.register(FarmerProfile)
class FarmerProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "role",
        "location_label",
        "latitude",
        "longitude",
        "onboarding_complete",
    )
    list_filter = ("role", "onboarding_complete")
    search_fields = ("user__username", "user__email", "location_label", "phone")
    actions = ("mark_onboarding_complete", "mark_onboarding_incomplete")

    @admin.action(description="Mark selected profiles as onboarding complete")
    def mark_onboarding_complete(self, request, queryset):
        updated = queryset.update(onboarding_complete=True)
        self.message_user(request, f"Updated {updated} profile(s).")

    @admin.action(description="Mark selected profiles as onboarding incomplete")
    def mark_onboarding_incomplete(self, request, queryset):
        updated = queryset.update(onboarding_complete=False)
        self.message_user(request, f"Updated {updated} profile(s).")


@admin.register(GrowingZone)
class GrowingZoneAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug")


@admin.register(Crop)
class CropAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "growing_zone",
        "plant_start_month",
        "plant_end_month",
        "harvest_start_month",
        "harvest_end_month",
    )
    list_filter = ("growing_zone", "rain_sensitive")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug")


@admin.register(FarmerCrop)
class FarmerCropAdmin(admin.ModelAdmin):
    list_display = ("profile", "crop", "is_primary")
    list_filter = ("is_primary",)
    search_fields = ("profile__user__username", "crop__name")


@admin.register(WeatherSnapshot)
class WeatherSnapshotAdmin(admin.ModelAdmin):
    list_display = ("profile", "latitude", "longitude", "fetched_at")
    search_fields = ("profile__user__username", "profile__location_label")


@admin.register(AdvisoryRule)
class AdvisoryRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "value", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "key", "value")
    prepopulated_fields = {"key": ("name",)}


@admin.register(WeatherDataSource)
class WeatherDataSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "base_url", "is_primary", "is_active", "updated_at")
    list_filter = ("is_primary", "is_active")
    search_fields = ("name", "base_url")


@admin.register(AdvisoryMessage)
class AdvisoryMessageAdmin(admin.ModelAdmin):
    list_display = ("profile", "crop", "severity", "generated_at")
    list_filter = ("severity", "generated_at")
    search_fields = ("profile__user__username", "crop__name", "weather_notes")


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        "profile",
        "sms_enabled",
        "emergency_only",
        "voice_enabled",
        "verified_phone",
        "updated_at",
    )
    list_filter = ("sms_enabled", "emergency_only", "voice_enabled", "verified_phone")
    search_fields = ("profile__user__username", "profile__phone")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("profile", "channel", "category", "status", "retry_count", "created_at", "sent_at")
    list_filter = ("channel", "category", "status")
    search_fields = ("profile__user__username", "message", "provider_message_id")


@admin.register(AdminAuditLog)
class AdminAuditLogAdmin(admin.ModelAdmin):
    list_display = ("actor", "action", "target_type", "target_id", "created_at")
    list_filter = ("action", "target_type")
    search_fields = ("actor__username", "target_type", "target_id", "details")
