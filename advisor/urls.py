from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "advisor"

urlpatterns = [
    path("", views.home, name="home"),

    # Auth
    path("accounts/register/", views.register, name="register"),
    path("accounts/login/", views.AdvisorLoginView.as_view(), name="login"),
    path(
        "accounts/logout/",
        auth_views.LogoutView.as_view(next_page="advisor:home"),
        name="logout",
    ),

    # SMS-based password reset
    path("accounts/forgot-password/", views.sms_password_reset_request, name="sms_password_reset_request"),
    path("accounts/forgot-password/verify/", views.sms_password_reset_verify, name="sms_password_reset_verify"),
    path("accounts/forgot-password/done/", views.sms_password_reset_complete, name="sms_password_reset_complete"),

    # Core farmer pages
    path("onboarding/", views.onboarding, name="onboarding"),
    path("advisory-preference/", views.advisory_preference_setup, name="advisory_preference_setup"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("profile/", views.profile_settings, name="profile_settings"),

    # Crops
    path("crops/", views.crop_library, name="crop_library"),
    path("crops/<slug:slug>/", views.crop_detail, name="crop_detail"),
    path("crops/<slug:slug>/track/", views.crop_track, name="crop_track"),
    path("crops/<slug:slug>/untrack/", views.crop_untrack, name="crop_untrack"),

    # Notifications
    path("notifications/preferences/", views.notification_preferences, name="notification_preferences"),
    path("notifications/history/", views.notification_history, name="notification_history"),

    # Admin panel
    path("admin-panel/", views.admin_panel, name="admin_panel"),
    path("admin-panel/users/", views.admin_users, name="admin_users"),
    path("admin-panel/rules/", views.admin_rules, name="admin_rules"),
    path("admin-panel/rules/<int:rule_id>/edit/", views.admin_rule_edit, name="admin_rule_edit"),
    path("admin-panel/rules/<int:rule_id>/delete/", views.admin_rule_delete, name="admin_rule_delete"),
    path("admin-panel/weather-sources/", views.admin_weather_sources, name="admin_weather_sources"),
    path("admin-panel/advisory-history/", views.admin_advisory_history, name="admin_advisory_history"),
    path("admin-panel/crops/", views.admin_crops, name="admin_crops"),
    path("admin-panel/crops/<int:crop_id>/edit/", views.admin_crop_edit, name="admin_crop_edit"),
    path("admin-panel/register-farmer/", views.admin_register_farmer, name="admin_register_farmer"),
    path("admin-panel/broadcast-sms/", views.admin_broadcast_sms, name="admin_broadcast_sms"),
]
