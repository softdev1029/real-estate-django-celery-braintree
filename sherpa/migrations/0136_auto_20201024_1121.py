# Generated by Django 2.2.13 on 2020-10-24 11:21

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0135_phonetype_last_carrier_lookup'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='prospect',
            name='is_phone_type_checked',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='last_message_error',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='last_message_status',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='mailing_address_obj',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='property_address_obj',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='synced_dnc',
        ),
    ]
