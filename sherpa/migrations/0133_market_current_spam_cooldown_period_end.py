# Generated by Django 2.2.13 on 2020-10-14 21:27

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0132_prospect_uuid_token'),
    ]

    operations = [
        migrations.AddField(
            model_name='market',
            name='current_spam_cooldown_period_end',
            field=models.DateTimeField(blank=True, help_text='Date time when spam cooldown ends.', null=True),
        ),
    ]
