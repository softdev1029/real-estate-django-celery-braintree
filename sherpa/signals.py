import requests

from django.conf import settings
from django.db.models.signals import post_save

from campaigns.models import CampaignAggregatedStats
from .models import (
    Campaign,
    FeatureNotification,
    UserFeatureNotification,
    UserProfile,
    ZapierWebhook,
)


def zapier_post_save(sender, instance, created, raw, **kwargs):
    if not created or settings.TEST_MODE:
        return

    # Upon creation, send a test request to the zapier webhook url.
    if instance.webhook_type == ZapierWebhook.Type.PROSPECT:
        data = {
            'lead_fullname': 'John Doe',
            'lead_first_name': 'John',
            'lead_last_name': 'Doe',
            'lead_email_address': 'johndoe@email.com',
            'campaign_name': 'Test Campaign Name',
            'lead_stage': 'Test Lead Stage',
            'sherpa_phone_number': '(444) 444-4444',
            'custom_field': 'Text from',
            'custom_field2': 'Custom field #2',
            'custom_field3': 'Custom field #3',
            'custom_field4': 'Custom field #4',
            'property_address_one_line': '123 Main St. Denver, CO 80001',
            'property_street': '123 Main St',
            'property_city': 'Denver',
            'property_state': 'CO',
            'property_zipcode': '80001',
            'property_phone': '(555) 555-5555',
            'mailing_street': '123 Mail St',
            'mailing_city': 'Boulder',
            'mailing_state': 'CO',
            'mailing_zipcode': '80301',
            'mailing_phone': '(444) 444-4444',
            'sherpa_conversation_link': settings.APP_URL,
            'prospect_link': settings.APP_URL,
            'notes': [
                'this is the first test note.',
                'this is the second test note.',
            ],
            'agent': 'Kevin Smith',
        }
    elif instance.webhook_type == ZapierWebhook.Type.SMS:
        data = {
            'message': 'test message received',
            'formatted': 'John Doe: test message received',
        }

    requests.post(instance.webhook_url, json=data)


def set_default_webhook(sender, instance, created, *args, **kwargs):
    """
    Sets the companies default zapier webhook if this is their first and only webhook.
    """
    if kwargs.get('raw', False) or not created:
        # Don't run when loading fixtures or when updating.
        return False

    company = instance.company
    count = ZapierWebhook.objects.filter(company=company).exclude(pk=instance.pk).count()
    if count == 0:
        company.default_zapier_webhook = instance
        company.save(update_fields=['default_zapier_webhook'])


def create_campaign_aggregate_stats(sender, instance, created, **kwargs):
    """
    Create CampaignAggregatedStats for new Campaigns
    """
    if created:
        instance.campaign_stats = CampaignAggregatedStats.objects.create()
        instance.save(update_fields=['campaign_stats'])


def feature_notification_post_save(sender, instance, created, **kwargs):
    """
    Bulk create of user feature notifications.
    """
    if created:
        def get_user_feature_notification_obj(user_profile_id):
            return UserFeatureNotification(
                user_profile_id=user_profile_id,
                feature_notification=instance,
            )

        user_profile_ids = UserProfile.objects.values_list('id', flat=True)
        user_feature_notification_objects = list(map(
            get_user_feature_notification_obj,
            user_profile_ids,
        ))
        UserFeatureNotification.objects.bulk_create(
            user_feature_notification_objects,
            ignore_conflicts=True,
        )


post_save.connect(create_campaign_aggregate_stats, sender=Campaign)
post_save.connect(zapier_post_save, sender=ZapierWebhook)
post_save.connect(set_default_webhook, sender=ZapierWebhook)
post_save.connect(feature_notification_post_save, sender=FeatureNotification)
