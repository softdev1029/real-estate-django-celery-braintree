# Generated by Django 2.2.12 on 2020-05-23 11:01

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0043_remove_campaignprospect_podio_url'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='campaignprospect',
            name='podio_app_id',
        ),
        migrations.RemoveField(
            model_name='campaignprospect',
            name='podio_app_token',
        ),
        migrations.RemoveField(
            model_name='campaignprospect',
            name='podio_lead_id',
        ),
    ]
