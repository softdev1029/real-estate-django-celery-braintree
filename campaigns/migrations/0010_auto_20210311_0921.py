# Generated by Django 2.2.13 on 2021-03-11 09:21

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0009_directmailcampaign_directmailorder_directmailreturnaddress'),
    ]

    operations = [
        migrations.CreateModel(
            name='DirectMailCampaignStats',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('total_delivered_pieces', models.PositiveSmallIntegerField(default=0)),
                ('delivery_rate', models.PositiveSmallIntegerField(default=0)),
                ('total_undelivered_pieces', models.PositiveSmallIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddField(
            model_name='directmailcampaign',
            name='dm_campaign_stats',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='dm_campaign', to='campaigns.DirectMailCampaignStats'),
        ),
    ]
