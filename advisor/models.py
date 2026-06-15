from django.conf import settings
from django.db import models


class FarmerProfile(models.Model):
    class UserRole(models.TextChoices):
        FARMER = "farmer", "Farmer"
        EXTENSION_OFFICER = "extension_officer", "Extension Officer"
        ADMIN = "admin", "Admin"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="farmer_profile",
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_label = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    onboarding_complete = models.BooleanField(default=False)
    role = models.CharField(
        max_length=32,
        choices=UserRole.choices,
        default=UserRole.FARMER,
    )

    def __str__(self):
        return f"Profile({self.user.username})"

    def has_coordinates(self):
        return self.latitude is not None and self.longitude is not None

    def is_admin_role(self):
        return self.role == self.UserRole.ADMIN or self.user.is_staff


class GrowingZone(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)

    def __str__(self):
        return self.name


class Crop(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    category = models.CharField(max_length=80, blank=True)
    description = models.TextField(blank=True)
    growing_zone = models.ForeignKey(
        GrowingZone,
        on_delete=models.PROTECT,
        related_name="crops",
    )
    plant_start_month = models.PositiveSmallIntegerField(help_text="1-12")
    plant_end_month = models.PositiveSmallIntegerField(help_text="1-12")
    harvest_start_month = models.PositiveSmallIntegerField(help_text="1-12")
    harvest_end_month = models.PositiveSmallIntegerField(help_text="1-12")
    min_temp_c = models.SmallIntegerField(
        null=True,
        blank=True,
        help_text="Rough minimum safe temp for planting (C)",
    )
    max_temp_c = models.SmallIntegerField(
        null=True,
        blank=True,
        help_text="Rough heat stress threshold (C)",
    )
    rain_sensitive = models.BooleanField(
        default=False,
        help_text="If true, heavy rain windows reduce planting score",
    )
    image = models.ImageField(
        upload_to="crops/",
        blank=True,
        help_text="Optional photo shown in the crop library and detail page",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class FarmerCrop(models.Model):
    profile = models.ForeignKey(
        FarmerProfile,
        on_delete=models.CASCADE,
        related_name="farmer_crops",
    )
    crop = models.ForeignKey(Crop, on_delete=models.CASCADE, related_name="farmer_links")
    is_primary = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "crop"],
                name="unique_farmer_crop",
            )
        ]

    def __str__(self):
        return f"{self.profile.user.username} — {self.crop.name}"


class WeatherSnapshot(models.Model):
    profile = models.OneToOneField(
        FarmerProfile,
        on_delete=models.CASCADE,
        related_name="weather_snapshot",
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    payload = models.JSONField()
    fetched_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Weather({self.profile.user.username})"


class AdvisoryRule(models.Model):
    name = models.CharField(max_length=120, unique=True)
    key = models.SlugField(unique=True)
    value = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class WeatherDataSource(models.Model):
    name = models.CharField(max_length=120, unique=True)
    base_url = models.URLField()
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class AdvisoryMessage(models.Model):
    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        EMERGENCY = "emergency", "Emergency"

    profile = models.ForeignKey(
        FarmerProfile,
        on_delete=models.CASCADE,
        related_name="advisory_messages",
    )
    crop = models.ForeignKey(Crop, on_delete=models.CASCADE, related_name="advisory_messages")
    planting_status = models.CharField(max_length=80)
    planting_detail = models.TextField()
    harvest_status = models.CharField(max_length=80)
    harvest_detail = models.TextField()
    weather_notes = models.TextField(blank=True)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.INFO)
    weather_payload = models.JSONField(default=dict, blank=True)
    location_label_snapshot = models.CharField(max_length=255, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self):
        return f"Advisory({self.profile.user.username}, {self.crop.name})"


class NotificationPreference(models.Model):
    class AdvisoryPreference(models.TextChoices):
        BOTH = "both", "Both Planting & Harvest"
        PLANTING = "planting", "Planting Only"
        HARVEST = "harvest", "Harvest Only"

    class Language(models.TextChoices):
        ENGLISH = "en", "English"
        SWAHILI = "sw", "Kiswahili"

    profile = models.OneToOneField(
        FarmerProfile,
        on_delete=models.CASCADE,
        related_name="notification_preference",
    )
    sms_enabled = models.BooleanField(default=False)
    emergency_only = models.BooleanField(default=False)
    voice_enabled = models.BooleanField(default=False)
    verified_phone = models.BooleanField(default=False)
    advisory_preference = models.CharField(
        max_length=16,
        choices=AdvisoryPreference.choices,
        null=True,
        blank=True,
        help_text="Which advisory type the farmer wants to receive. Null = not yet chosen.",
    )
    language = models.CharField(
        max_length=4,
        choices=Language.choices,
        default=Language.ENGLISH,
        help_text="Language for advisory SMS messages.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"NotificationPreference({self.profile.user.username})"


class Notification(models.Model):
    class Channel(models.TextChoices):
        SMS = "sms", "SMS"
        VOICE = "voice", "Voice"

    class Category(models.TextChoices):
        WEATHER_UPDATE = "weather_update", "Weather Update"
        ADVISORY = "advisory", "Advisory"
        EMERGENCY = "emergency", "Emergency"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    profile = models.ForeignKey(
        FarmerProfile,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.SMS)
    category = models.CharField(max_length=30, choices=Category.choices)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    retry_count = models.PositiveSmallIntegerField(default=0)
    error_message = models.TextField(blank=True)
    provider_message_id = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Notification({self.profile.user.username}, {self.category}, {self.status})"


class PasswordResetOTP(models.Model):
    """Single-use 6-digit OTP for SMS-based password reset."""

    phone = models.CharField(max_length=20)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def is_valid(self):
        from django.utils import timezone
        return not self.is_used and self.expires_at > timezone.now()

    def __str__(self):
        return f"OTP({self.phone}, used={self.is_used})"


class AdminAuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admin_audit_logs",
    )
    action = models.CharField(max_length=120)
    target_type = models.CharField(max_length=80)
    target_id = models.CharField(max_length=64, blank=True)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Audit({self.action}, {self.target_type})"
