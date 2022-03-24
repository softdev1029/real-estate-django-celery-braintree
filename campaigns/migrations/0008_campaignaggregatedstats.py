# Generated by Django 2.2.13 on 2020-11-10 22:34

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0007_auto_20200911_1333'),
    ]

    operations = [
        migrations.CreateModel(
            name='CampaignAggregatedStats',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('total_priority', models.PositiveSmallIntegerField(default=0)),
                ('total_sms_followups', models.IntegerField(default=0)),
                ('total_skipped', models.IntegerField(default=0)),
                ('total_dnc_count', models.IntegerField(default=0)),
                ('total_sms_sent_count', models.IntegerField(default=0)),
                ('total_sms_received_count', models.IntegerField(default=0)),
                ('total_wrong_number_count', models.IntegerField(default=0)),
                ('total_auto_dead_count', models.IntegerField(default=0)),
                ('total_initial_sent_skipped', models.IntegerField(default=0)),
                ('total_mobile', models.IntegerField(default=0)),
                ('total_landline', models.IntegerField(default=0)),
                ('total_phone_other', models.IntegerField(default=0)),
                ('total_intial_sms_sent_today_count', models.IntegerField(default=0)),
                ('total_leads', models.IntegerField(default=0)),
                ('has_delivered_sms_only_count', models.IntegerField(default=0)),
            ],
        ),
    ]
