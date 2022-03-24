# Generated by Django 2.2.13 on 2021-03-11 14:00

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0008_auto_20210311_1400'),
        ('campaigns', '0011_auto_20210311_0851'),
    ]

    operations = [
        migrations.AddField(
            model_name='directmailcampaign',
            name='dm_transaction',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='billing.Transaction'),
        ),
        migrations.AlterField(
            model_name='directmailorder',
            name='status',
            field=models.CharField(blank=True, choices=[('processing', 'processing'), ('complete', 'complete'), ('failed', 'failed'), ('locked', 'locked'), ('incomplete', 'incomplete')], max_length=255, null=True),
        ),
    ]
