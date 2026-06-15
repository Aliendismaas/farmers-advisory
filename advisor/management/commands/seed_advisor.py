from django.core.management.base import BaseCommand
from django.utils.text import slugify

from advisor.models import Crop, GrowingZone


# Iringa Region crop calendars.
# Iringa has a unimodal rainfall pattern (single rainy season):
#   Long rains (Masika): November – April
#   Dry season:          May – October
# The region sits at 1,600–2,200 m elevation, giving cooler highland temperatures.
# Many vegetables and Irish potatoes are also produced under irrigation in the dry season.
CROPS = [
    {
        "name": "Maize",
        "category": "Cereal",
        "description": (
            "The primary staple crop of Iringa Region. Planted at the onset of the long rains "
            "(November–January) and harvested before the dry season. Requires 90–120 days to "
            "maturity depending on the variety."
        ),
        "plant_start_month": 11,
        "plant_end_month": 1,
        "harvest_start_month": 4,
        "harvest_end_month": 6,
        "min_temp_c": 10,
        "max_temp_c": 30,
        "rain_sensitive": True,
    },
    {
        "name": "Wheat",
        "category": "Cereal",
        "description": (
            "Grown in the cooler highlands of Mufindi and Iringa districts. "
            "Planted during the rainy season and harvested in the dry months. "
            "Requires well-drained soils and moderate temperatures."
        ),
        "plant_start_month": 11,
        "plant_end_month": 1,
        "harvest_start_month": 5,
        "harvest_end_month": 7,
        "min_temp_c": 5,
        "max_temp_c": 24,
        "rain_sensitive": True,
    },
    {
        "name": "Sorghum",
        "category": "Cereal",
        "description": (
            "Drought-tolerant cereal grown in the drier lowland parts of Iringa Region. "
            "Planted at the onset of the rains; important food security crop."
        ),
        "plant_start_month": 11,
        "plant_end_month": 1,
        "harvest_start_month": 4,
        "harvest_end_month": 6,
        "min_temp_c": 12,
        "max_temp_c": 38,
        "rain_sensitive": False,
    },
    {
        "name": "Irish potatoes",
        "category": "Root / tuber",
        "description": (
            "A major commercial crop of Iringa highland areas. The cool temperatures and fertile "
            "soils are ideal. Main season follows the long rains; a smaller irrigated crop is "
            "possible in the dry season in some areas."
        ),
        "plant_start_month": 10,
        "plant_end_month": 12,
        "harvest_start_month": 2,
        "harvest_end_month": 4,
        "min_temp_c": 7,
        "max_temp_c": 22,
        "rain_sensitive": True,
    },
    {
        "name": "Sweet potatoes",
        "category": "Root / tuber",
        "description": (
            "Popular food and income crop across Iringa Region. Planted at the start of the rains "
            "and tolerates moderate dry spells better than Irish potatoes."
        ),
        "plant_start_month": 11,
        "plant_end_month": 1,
        "harvest_start_month": 4,
        "harvest_end_month": 6,
        "min_temp_c": 15,
        "max_temp_c": 30,
        "rain_sensitive": False,
    },
    {
        "name": "Common beans",
        "category": "Legume",
        "description": (
            "Important food and cash legume throughout Iringa Region. Short season (60–90 days) "
            "fits well within the long-rains window. Also grown as a relay crop with maize."
        ),
        "plant_start_month": 11,
        "plant_end_month": 1,
        "harvest_start_month": 3,
        "harvest_end_month": 5,
        "min_temp_c": 12,
        "max_temp_c": 28,
        "rain_sensitive": True,
    },
    {
        "name": "Groundnuts",
        "category": "Legume",
        "description": (
            "Grown in the warmer and lower-altitude parts of Iringa Region. "
            "Planted at the onset of the long rains; sensitive to waterlogging at podding stage."
        ),
        "plant_start_month": 11,
        "plant_end_month": 12,
        "harvest_start_month": 4,
        "harvest_end_month": 5,
        "min_temp_c": 18,
        "max_temp_c": 33,
        "rain_sensitive": True,
    },
    {
        "name": "Sunflower",
        "category": "Oilseed",
        "description": (
            "Grown across Iringa Region as a cash crop for cooking oil. "
            "Tolerates drier conditions and is planted at the start of the long rains."
        ),
        "plant_start_month": 11,
        "plant_end_month": 1,
        "harvest_start_month": 4,
        "harvest_end_month": 6,
        "min_temp_c": 10,
        "max_temp_c": 32,
        "rain_sensitive": False,
    },
    {
        "name": "Tomatoes",
        "category": "Vegetable",
        "description": (
            "Grown mainly under irrigation during the dry season in Iringa. "
            "Often transplanted 4–6 weeks after seed sowing. "
            "High-value crop for local and regional markets."
        ),
        "plant_start_month": 6,
        "plant_end_month": 8,
        "harvest_start_month": 9,
        "harvest_end_month": 11,
        "min_temp_c": 15,
        "max_temp_c": 30,
        "rain_sensitive": True,
    },
    {
        "name": "Onions",
        "category": "Vegetable",
        "description": (
            "Iringa is one of Tanzania's leading onion-producing regions. "
            "Grown as a dry-season irrigated crop; known for long shelf life and "
            "strong demand in domestic and export markets."
        ),
        "plant_start_month": 6,
        "plant_end_month": 8,
        "harvest_start_month": 10,
        "harvest_end_month": 12,
        "min_temp_c": 12,
        "max_temp_c": 30,
        "rain_sensitive": True,
    },
    {
        "name": "Cabbage",
        "category": "Vegetable",
        "description": (
            "Cool-season crop that thrives in Iringa's highland climate year-round. "
            "Main production during the dry season under irrigation. "
            "Popular in local markets."
        ),
        "plant_start_month": 6,
        "plant_end_month": 8,
        "harvest_start_month": 9,
        "harvest_end_month": 11,
        "min_temp_c": 8,
        "max_temp_c": 25,
        "rain_sensitive": True,
    },
    {
        "name": "Avocado",
        "category": "Fruit",
        "description": (
            "Iringa Region is one of Tanzania's major avocado producers. "
            "Trees are long-lived perennials; main harvest season is June–October. "
            "Grown widely in Kilolo and Iringa districts for domestic and export markets."
        ),
        "plant_start_month": 3,
        "plant_end_month": 5,
        "harvest_start_month": 6,
        "harvest_end_month": 10,
        "min_temp_c": 10,
        "max_temp_c": 28,
        "rain_sensitive": False,
    },
]


class Command(BaseCommand):
    help = "Seed growing zone and crops for Iringa Region, Tanzania."

    def handle(self, *args, **options):
        # Migrate old zone names to the Iringa Region zone
        old_zone = GrowingZone.objects.filter(slug="tanzania").first()
        if old_zone:
            old_zone.name = "Iringa Region"
            old_zone.slug = "iringa-region"
            old_zone.save()
            zone = old_zone
            self.stdout.write(self.style.WARNING("Renamed existing 'Tanzania' zone to 'Iringa Region'."))
        else:
            zone, _ = GrowingZone.objects.get_or_create(
                slug="iringa-region",
                defaults={"name": "Iringa Region"},
            )

        # Remove crops that are not relevant to Iringa Region
        irrelevant_slugs = [
            "paddy-rice",
            "cassava",
            "sesame-simsim",
            "cotton",
            "maize-vuli-season",
            "maize-grain",  # replaced by the simpler "maize"
        ]
        removed = 0
        for slug in irrelevant_slugs:
            deleted, _ = Crop.objects.filter(slug=slug).delete()
            removed += deleted

        created = 0
        updated = 0
        for row in CROPS:
            slug = slugify(row["name"])[:120]
            obj, was_created = Crop.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": row["name"],
                    "category": row["category"],
                    "description": row["description"],
                    "growing_zone": zone,
                    "plant_start_month": row["plant_start_month"],
                    "plant_end_month": row["plant_end_month"],
                    "harvest_start_month": row["harvest_start_month"],
                    "harvest_end_month": row["harvest_end_month"],
                    "min_temp_c": row["min_temp_c"],
                    "max_temp_c": row["max_temp_c"],
                    "rain_sensitive": row["rain_sensitive"],
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Zone: {zone.name}. Crops created={created}, updated={updated}, removed={removed}."
            )
        )
