# Generated by Django 2.2.13 on 2020-08-29 10:57

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0105_auto_20200828_1115'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='activity',
            name='campaign_prospect',
        ),
        migrations.RemoveField(
            model_name='activity',
            name='date_local',
        ),
    ]
