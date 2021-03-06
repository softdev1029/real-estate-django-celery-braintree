# Generated by Django 2.2.13 on 2020-10-17 11:33

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0132_prospect_uuid_token'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='prospect',
            name='fullname',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='has_sms_send_received_checked',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='phone_caller_id_name',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='phone_formatted_display',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='phone_formatted_twilio',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='phone_type_checked_datetime',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='reminder_email_address',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='reminder_tz',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='send_notification_dt',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='sherpa_phone_number',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='sherpa_phone_number_status',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='total_sms_sent_received_count',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_city_name',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_default_city_name',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_extra_secondary_designator',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_extra_secondary_number',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_last_line',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_pmb_designator',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_pmb_number',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_precision',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_primary_number',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_secondary_designator',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_secondary_number',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_state_abbreviation',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_street_name',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_street_postdirection',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_street_predirection',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_street_suffix',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_time_zone',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_utc_offset',
        ),
        migrations.RemoveField(
            model_name='prospect',
            name='validated_property_zipcode',
        ),
    ]
