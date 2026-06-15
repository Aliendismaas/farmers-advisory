from django.core.management.base import BaseCommand

from advisor.services import refresh_weather_for_active_profiles


class Command(BaseCommand):
    help = "Refresh weather snapshots for all active farmer profiles."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-profiles",
            type=int,
            default=None,
            help="Limit how many profiles to refresh in this run.",
        )

    def handle(self, *args, **options):
        stats = refresh_weather_for_active_profiles(max_profiles=options["max_profiles"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Weather refresh complete. refreshed={stats['refreshed']} failed={stats['failed']}"
            )
        )
