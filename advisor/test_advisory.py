from datetime import date

from django.test import TestCase

from advisor.advisory import advise_crop, month_in_planting_window


class MonthWindowTests(TestCase):
    def test_simple_range(self):
        self.assertTrue(month_in_planting_window(5, 3, 7))
        self.assertFalse(month_in_planting_window(2, 3, 7))

    def test_wrap_range(self):
        self.assertTrue(month_in_planting_window(11, 10, 3))
        self.assertTrue(month_in_planting_window(1, 10, 3))
        self.assertFalse(month_in_planting_window(5, 10, 3))


class AdvisoryTests(TestCase):
    def test_favorable_planting_month(self):
        payload = {
            "daily": {
                "temperature_2m_min": [12.0] * 14,
                "temperature_2m_max": [26.0] * 14,
                "precipitation_sum": [2.0] * 14,
            }
        }
        adv = advise_crop(
            crop_name="Test",
            plant_start=10,
            plant_end=12,
            harvest_start=4,
            harvest_end=7,
            min_temp_c=10,
            max_temp_c=38,
            rain_sensitive=True,
            today=date(2026, 11, 15),
            forecast_payload=payload,
        )
        self.assertEqual(adv.planting_status, "In season")
        self.assertIn("planting window", adv.planting_detail)

    def test_marginal_from_frost(self):
        payload = {
            "daily": {
                "temperature_2m_min": [0.5] * 14,
                "temperature_2m_max": [18.0] * 14,
                "precipitation_sum": [0.0] * 14,
            }
        }
        adv = advise_crop(
            crop_name="Test",
            plant_start=10,
            plant_end=12,
            harvest_start=4,
            harvest_end=7,
            min_temp_c=10,
            max_temp_c=38,
            rain_sensitive=True,
            today=date(2026, 11, 15),
            forecast_payload=payload,
        )
        self.assertEqual(adv.planting_status, "Marginal")
