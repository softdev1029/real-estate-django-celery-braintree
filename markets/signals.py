from django.db.models.signals import post_save

from sherpa.models import Market


def market_post_save(sender, instance, created, **kwargs):
    """
    Create messaging profile id if one doesn't exist.
    """
    if instance.name == 'Twilio':
        return

    if instance.is_active and not instance.messaging_profile_id:
        client = instance.company.messaging_client
        mp_id = client.create_messaging_profile(instance)
        instance.messaging_profile_id = mp_id
        instance.save()


post_save.connect(market_post_save, sender=Market)
