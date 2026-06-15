import re

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password

from .models import AdvisoryRule, Crop, FarmerProfile, GrowingZone, NotificationPreference, WeatherDataSource

_TZ_PHONE_RE = re.compile(r"^255[67]\d{8}$")


def _normalize_and_validate_tz_phone(raw: str) -> str:
    """Return normalized 255XXXXXXXXX or raise ValidationError."""
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 12 and digits.startswith("255"):
        pass
    elif len(digits) == 10 and digits.startswith("0"):
        digits = "255" + digits[1:]
    elif len(digits) == 9 and digits[0] in ("6", "7"):
        digits = "255" + digits
    else:
        raise forms.ValidationError(
            "Enter a valid Tanzania number (e.g. 255712345678)."
        )
    if not _TZ_PHONE_RE.match(digits):
        raise forms.ValidationError(
            "The number after 255 must start with 6 or 7 followed by 8 digits."
        )
    return digits


class PhoneAuthenticationForm(AuthenticationForm):
    """Login form that labels the username field as Phone number."""

    username = forms.CharField(
        label="Phone number",
        max_length=32,
        widget=forms.TextInput(
            attrs={
                "autofocus": True,
                "placeholder": "712 345 678",
                "autocomplete": "username",
                "inputmode": "numeric",
            }
        ),
    )

    def clean_username(self):
        """Normalize any Tanzania phone format to 255XXXXXXXXX before lookup."""
        raw = self.cleaned_data.get("username", "").strip()
        digits = "".join(c for c in raw if c.isdigit())
        if len(digits) == 12 and digits.startswith("255"):
            return digits
        if len(digits) == 10 and digits.startswith("0"):
            return "255" + digits[1:]
        if len(digits) == 9 and digits[0] in ("6", "7"):
            return "255" + digits
        return raw
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "current-password",
                "placeholder": "Enter your password",
            }
        ),
    )

    error_messages = {
        "invalid_login": (
            "The phone number or password you entered is incorrect. "
            "Please check and try again."
        ),
        "inactive": "This account has been disabled.",
    }


class SignUpForm(forms.Form):
    """Registration form using phone number as the primary identifier."""

    phone_number = forms.CharField(
        max_length=32,
        required=True,
        label="Phone number",
        widget=forms.TextInput(
            attrs={
                "placeholder": "712 345 678",
                "autocomplete": "username",
                "inputmode": "numeric",
            }
        ),
    )
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Create a strong password",
                "autocomplete": "new-password",
            }
        ),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Repeat your password",
                "autocomplete": "new-password",
            }
        ),
    )

    def clean_phone_number(self):
        phone = (self.cleaned_data.get("phone_number") or "").strip()
        if not phone:
            raise forms.ValidationError("Phone number is required.")
        phone = _normalize_and_validate_tz_phone(phone)
        if User.objects.filter(username=phone).exists():
            raise forms.ValidationError(
                "This phone number is already registered. Try signing in instead."
            )
        return phone

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        return p2

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password1")
        phone = cleaned.get("phone_number", "")
        if password and phone:
            temp_user = User(username=phone)
            try:
                validate_password(password, temp_user)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    def save(self, commit=True):
        phone = self.cleaned_data["phone_number"].strip()
        password = self.cleaned_data["password1"]
        user = User(username=phone)
        user.set_password(password)
        if commit:
            user.save()
        return user


class ManualLocationForm(forms.Form):
    """Direct coordinates entry (e.g. from maps)."""

    latitude = forms.DecimalField(max_digits=9, decimal_places=6)
    longitude = forms.DecimalField(max_digits=9, decimal_places=6)
    location_label = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"placeholder": "Farm / village name (optional)"}),
    )


class LocationSearchForm(forms.Form):
    q = forms.CharField(
        label="Search place",
        required=True,
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Mafinga, Isimani, Iringa Town..."}),
    )


class ProfileSettingsForm(forms.Form):
    """User-facing profile update form."""

    phone = forms.CharField(
        max_length=32,
        required=False,
        label="Phone number",
        help_text="This is your login identifier — changing it will update your login.",
        widget=forms.TextInput(attrs={"placeholder": "712 345 678", "inputmode": "numeric"}),
    )

    def __init__(self, *args, user=None, profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user
        self._profile = profile
        if profile:
            self.fields["phone"].initial = profile.phone

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        if not phone:
            return phone
        phone = _normalize_and_validate_tz_phone(phone)
        if (
            self._user
            and User.objects.filter(username=phone)
            .exclude(pk=self._user.pk)
            .exists()
        ):
            raise forms.ValidationError("This phone number is already used by another account.")
        return phone


class CropForm(forms.ModelForm):
    class Meta:
        model = Crop
        fields = (
            "name",
            "category",
            "description",
            "growing_zone",
            "plant_start_month",
            "plant_end_month",
            "harvest_start_month",
            "harvest_end_month",
            "min_temp_c",
            "max_temp_c",
            "rain_sensitive",
            "image",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }
        help_texts = {
            "plant_start_month": "Month number 1–12",
            "plant_end_month": "Month number 1–12",
            "harvest_start_month": "Month number 1–12",
            "harvest_end_month": "Month number 1–12",
        }


class AdvisoryRuleForm(forms.ModelForm):
    class Meta:
        model = AdvisoryRule
        fields = ("name", "key", "value", "description", "is_active")


class WeatherDataSourceForm(forms.ModelForm):
    class Meta:
        model = WeatherDataSource
        fields = ("name", "base_url", "is_primary", "is_active", "notes")


class NotificationPreferenceForm(forms.ModelForm):
    class Meta:
        model = NotificationPreference
        fields = ("advisory_preference", "sms_enabled", "emergency_only", "voice_enabled", "language")


class BroadcastSmsForm(forms.Form):
    ADVISORY_TYPE_CHOICES = [
        ("all", "All Farmers"),
        ("planting", "Plant Advisory — farmers who want planting updates"),
        ("harvest", "Harvest Advisory — farmers who want harvest updates"),
    ]

    crop = forms.ModelChoiceField(
        queryset=Crop.objects.order_by("name"),
        empty_label="— Select a crop —",
        label="Crop",
    )
    advisory_type = forms.ChoiceField(
        choices=ADVISORY_TYPE_CHOICES,
        label="Advisory Type",
        initial="all",
    )
    message = forms.CharField(
        label="Message",
        max_length=459,
        widget=forms.Textarea(
            attrs={"rows": 5, "placeholder": "Type your advisory message here..."}
        ),
    )


class RegisterFarmerForm(forms.Form):
    """Admin form to register an offline farmer (no smartphone)."""

    full_name = forms.CharField(
        max_length=120,
        label="Full name",
        widget=forms.TextInput(attrs={"placeholder": "e.g. John Mwenda"}),
    )
    phone = forms.CharField(
        max_length=32,
        label="Phone number",
        widget=forms.TextInput(attrs={"placeholder": "712 345 678", "inputmode": "numeric"}),
    )
    location_query = forms.CharField(
        max_length=200,
        label="Village / town in Iringa Region",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Mafinga, Isimani, Iringa Town"}),
    )
    crops = forms.ModelMultipleChoiceField(
        queryset=None,
        widget=forms.CheckboxSelectMultiple,
        label="Crops this farmer grows",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["crops"].queryset = Crop.objects.order_by("name")

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        phone = _normalize_and_validate_tz_phone(phone)
        if User.objects.filter(username=phone).exists():
            raise forms.ValidationError("A farmer with this phone number is already registered.")
        return phone


class SmsPasswordResetRequestForm(forms.Form):
    """Step 1: farmer enters phone number to receive an OTP."""

    phone = forms.CharField(
        max_length=32,
        label="Phone number",
        widget=forms.TextInput(
            attrs={
                "placeholder": "712 345 678",
                "inputmode": "numeric",
                "autofocus": True,
            }
        ),
    )

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        return _normalize_and_validate_tz_phone(phone)


class SmsPasswordResetVerifyForm(forms.Form):
    """Step 2: farmer enters OTP + new password."""

    code = forms.CharField(
        max_length=6,
        min_length=6,
        label="Verification code",
        widget=forms.TextInput(
            attrs={
                "placeholder": "6-digit code",
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "autofocus": True,
            }
        ),
    )
    new_password1 = forms.CharField(
        label="New password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Create a new password",
                "autocomplete": "new-password",
            }
        ),
    )
    new_password2 = forms.CharField(
        label="Confirm new password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Repeat your new password",
                "autocomplete": "new-password",
            }
        ),
    )

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip()
        if not code.isdigit():
            raise forms.ValidationError("The code must contain digits only.")
        return code

    def clean_new_password2(self):
        p1 = self.cleaned_data.get("new_password1")
        p2 = self.cleaned_data.get("new_password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        return p2

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("new_password1")
        if password:
            try:
                validate_password(password)
            except forms.ValidationError as exc:
                self.add_error("new_password1", exc)
        return cleaned
