from django.db.models.signals import post_save, pre_save

from sherpa.models import Company, SubscriptionCancellationRequest
from sms.models import CarrierApprovedTemplate, SMSTemplateCategory
from .tasks import modify_freshsuccess_account


def company_post_save(sender, instance, created, raw, **kwargs):
    """
    Create messaging profile id if one doesn't exist.
    """
    if raw:
        return

    if created:
        # Add all active carrier approved templates to the company.
        templates = CarrierApprovedTemplate.objects.filter(
            is_active=True,
        ).values_list('pk', flat=True)
        instance.carrier_templates.add(*templates)

        if not raw:
            # Add the standard template categories
            system_categories = ['Initial', 'Follow-up']
            for category in system_categories:
                SMSTemplateCategory.objects.get_or_create(company=instance, title=category)

        instance.create_property_tags()

    if not created:
        # For now we don't have anything in the signal for updates.
        return

    modify_freshsuccess_account.delay(instance.id)


def subscription_cancellation_request_pre_save(sender, instance, *args, **kwargs):
    """
    Saves the cancellation_date as the Company next_billing_date from their subscription.
    """
    if not instance._state.adding:
        return

    if not instance.cancellation_date:
        instance.cancellation_date = instance.company.next_billing_date


post_save.connect(company_post_save, sender=Company)
pre_save.connect(subscription_cancellation_request_pre_save, sender=SubscriptionCancellationRequest)
