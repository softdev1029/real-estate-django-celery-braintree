# Generated by Django 2.2.13 on 2020-08-28 11:15

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0104_merge_20200820_1658'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='campaignprospect',
            name='campaign_name',
        ),
        migrations.RemoveField(
            model_name='campaignprospect',
            name='first_message_error',
        ),
        migrations.RemoveField(
            model_name='campaignprospect',
            name='first_message_status',
        ),
        migrations.RemoveField(
            model_name='campaignprospect',
            name='prospect_name',
        ),
        migrations.RemoveField(
            model_name='campaignprospect',
            name='put_back_in_pool',
        ),
        migrations.RemoveField(
            model_name='campaignprospect',
            name='second_message_error',
        ),
        migrations.RemoveField(
            model_name='campaignprospect',
            name='second_message_status',
        ),
        migrations.RemoveField(
            model_name='campaignprospect',
            name='two_attempts_skip',
        ),
    ]
