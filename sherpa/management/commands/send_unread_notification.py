from django.conf import settings
from django.contrib.sites.models import Site
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone as django_tz

from sherpa.models import CampaignProspect, Prospect


class Command(BaseCommand):
    """
    Called every 10 minutes in a cron job.
    """
    def handle(self, *args, **options):
        """
        Send an email reminder with data about a prospect.
        """
        now = django_tz.now()
        prospect_list = Prospect.objects.filter(
            Q(has_reminder=True),
            Q(reminder_date_utc__lte=now),
            ~Q(reminder_email_sent=True),
            ~Q(reminder_agent=None),
        )

        for prospect in prospect_list:
            prospect.reminder_email_sent = True
            prospect.save(update_fields=['reminder_email_sent'])
            try:
                # get most recent campaign_prospect for link
                campaign_prospect_list = CampaignProspect.objects.filter(
                    prospect=prospect,
                ).order_by('-id')[:1]
                campaign_prospect = campaign_prospect_list[0]
                campaign_prospect_id = campaign_prospect.id
                lead_stage_title = campaign_prospect.prospect.lead_stage.lead_stage_title
                site = Site.objects.get(id=settings.DJOSER_SITE_ID)

                subject = 'Sherpa Reminder - Prospect: %s - %s' % (
                    prospect.name, prospect.address_display,
                )
                from_email = settings.DEFAULT_FROM_EMAIL
                to = prospect.reminder_agent.user.email
                text_content = 'Upload Complete'
                html_content = render_to_string(
                    'email/email_reminder.html',
                    {
                        'site': site,
                        'prospect': prospect,
                        'campaign_prospect_id': campaign_prospect_id,
                        'lead_stage_title': lead_stage_title,
                    },
                )
                email = EmailMultiAlternatives(subject, text_content, from_email, [to])
                email.attach_alternative(html_content, "text/html")

                email.send()
            except Exception:
                pass
