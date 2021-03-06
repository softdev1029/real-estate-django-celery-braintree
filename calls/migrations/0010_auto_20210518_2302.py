# Generated by Django 2.2.13 on 2021-05-18 23:02

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calls', '0009_auto_20210513_1931'),
    ]

    operations = [
        migrations.AlterField(
            model_name='call',
            name='error',
            field=models.CharField(blank=True, choices=[('no_sherpa_phone', 'No Sherpa Phone'), ('no_forwarding', 'No Forwarding Number'), ('error_forwarding', 'Error Forwarding'), ('no_prospect', 'No Prospect'), ('no_agent', 'No Agent'), ('api_error', 'Telnyx API Error'), ('duplicate_phone', ' Duplicate Phone'), ('call_inactive', 'Call Inactive')], max_length=16),
        ),
    ]
