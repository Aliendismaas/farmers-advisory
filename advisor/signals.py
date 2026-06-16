from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import FarmerProfile, NotificationPreference


@receiver(post_save, sender=User)
def create_farmer_profile(sender, instance, created, **kwargs):
    if kwargs.get('raw', False):
        return
    if created:
        profile, _ = FarmerProfile.objects.get_or_create(user=instance)
        NotificationPreference.objects.get_or_create(profile=profile)
