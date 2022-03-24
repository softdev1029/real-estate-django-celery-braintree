# Generated by Django 2.2.13 on 2020-11-18 18:27

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0008_campaignaggregatedstats'),
        ('sherpa', '0145_auto_20201118_0125'),
    ]

    def create_campaign_stats(apps, schema_editor):
        # We can't import the Person model directly as it may be a newer
        # version than this migration expects. We use the historical version.
        Campaign = apps.get_model('sherpa', 'Campaign')
        CampaignAggregatedStats = apps.get_model('campaigns', 'CampaignAggregatedStats')
        for campaign in Campaign.objects.all():
            campaign.campaign_stats = CampaignAggregatedStats.objects.create(
                total_priority=campaign.total_priority,
                total_sms_followups=campaign.total_sms_followups,
                total_skipped=campaign.total_skipped,
                total_dnc_count=campaign.total_dnc_count,
                total_sms_sent_count=campaign.total_sms_sent_count,
                total_sms_received_count=campaign.total_sms_received_count,
                total_wrong_number_count=campaign.total_wrong_number_count,
                total_auto_dead_count=campaign.total_auto_dead_count,
                total_initial_sent_skipped=campaign.total_initial_sent_skipped,
                total_mobile=campaign.total_mobile,
                total_landline=campaign.total_landline,
                total_phone_other=campaign.total_phone_other,
                total_intial_sms_sent_today_count=campaign.total_intial_sms_sent_today_count,
                total_leads=campaign.total_leads,
                has_delivered_sms_only_count=campaign.has_delivered_sms_only_count,
            )
            campaign.save(update_fields=['campaign_stats'])

    operations = [
        migrations.AddField(
            model_name='campaign',
            name='campaign_stats',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='campaigns.CampaignAggregatedStats'),
        ),
        migrations.RunPython(create_campaign_stats),
    ]