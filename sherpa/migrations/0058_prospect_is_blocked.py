# Generated by Django 2.2.13 on 2020-06-23 15:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0057_campaign_skip_prospects_who_messaged'),
    ]

    operations = [
        migrations.AddField(
            model_name='prospect',
            name='is_blocked',
            field=models.BooleanField(null=True),
        ),
    ]
