from django.core.management.base import BaseCommand

from sherpa.models import CampaignProspect, Company, SMSMessage


class Command(BaseCommand):
    """
    After loading the seed data, there are some data triggers that do not get handled correctly
    and need to be called separately.
    """
    def handle(self, *args, **options):
        # Set correct `has_unread_sms` to valid campaigns and campaign prospects.
        unread_messages = SMSMessage.objects.filter(unread_by_recipient=True)
        prospects = [message.prospect for message in unread_messages]
        campaign_prospects = CampaignProspect.objects.filter(prospect__in=prospects)

        for campaign_prospect in campaign_prospects:
            campaign = campaign_prospect.campaign
            if not campaign_prospect.has_unread_sms:
                campaign_prospect.has_unread_sms = True
                campaign_prospect.save()

                campaign_prospect.prospect.has_unread_sms = True
                campaign_prospect.prospect.save()

            if not campaign.has_unread_sms:
                campaign.has_unread_sms = True
                campaign.save()

        for company in Company.objects.all():
            company.create_property_tags()

        # George's company is constantly hitting the max address limit of braintree (50), so we need
        # to keep it clean so that this issue does not keep coming up.
        george_company = Company.objects.first()
        george_company.clear_braintree_addresses()
