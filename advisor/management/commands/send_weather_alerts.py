from django.core.management.base import BaseCommand

from advisor.models import FarmerProfile
from advisor.services import get_or_refresh_weather, maybe_send_emergency_alert


class Command(BaseCommand):
    help = "Scan profiles and send emergency weather SMS alerts."

    def handle(self, *args, **options):
        sent = 0
        for profile in FarmerProfile.objects.filter(onboarding_complete=True):
            payload, _ = get_or_refresh_weather(profile)
            notification = maybe_send_emergency_alert(profile, payload)
            if notification:
                sent += 1
        self.stdout.write(self.style.SUCCESS(f"Emergency alerts processed: sent={sent}"))
