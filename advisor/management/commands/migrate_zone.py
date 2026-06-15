"""
One-time command: rename the 'Tanzania' growing zone to 'Iringa Region'
and remove crops not cultivated in Iringa.

Run once on your existing database:
    python manage.py migrate_zone
"""
from django.core.management.base import BaseCommand

from advisor.models import Crop, GrowingZone

IRRELEVANT_CROP_SLUGS = [
    "paddy-rice",
    "cassava",
    "sesame-simsim",
    "cotton",
    "maize-vuli-season",
    "maize-grain",
]


class Command(BaseCommand):
    help = "Rename the Tanzania zone to Iringa Region and remove non-Iringa crops."

    def handle(self, *args, **options):
        # Rename zone
        zone = GrowingZone.objects.filter(slug="tanzania").first()
        if zone:
            zone.name = "Iringa Region"
            zone.slug = "iringa-region"
            zone.save()
            self.stdout.write(self.style.SUCCESS("Renamed zone: Tanzania → Iringa Region"))
        else:
            zone = GrowingZone.objects.filter(slug="iringa-region").first()
            if zone:
                self.stdout.write("Zone 'Iringa Region' already exists — no rename needed.")
            else:
                zone = GrowingZone.objects.create(name="Iringa Region", slug="iringa-region")
                self.stdout.write(self.style.SUCCESS("Created zone: Iringa Region"))

        # Remove non-Iringa crops
        removed = 0
        for slug in IRRELEVANT_CROP_SLUGS:
            deleted, _ = Crop.objects.filter(slug=slug).delete()
            if deleted:
                self.stdout.write(f"  Removed crop: {slug}")
            removed += deleted

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {removed} non-Iringa crop(s) removed."
            )
        )
