from django.apps import AppConfig


class AdvisorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "advisor"
    verbose_name = "Farmers Advisor"

    def ready(self):
        from . import signals  # noqa: F401
