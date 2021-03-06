# Generated by Django 2.2.12 on 2020-05-15 15:39

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0041_auto_20200513_1951'),
    ]

    operations = [
        migrations.AlterField(
            model_name='company',
            name='outgoing_company_names',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=32), blank=True, default=list, help_text='Comma seperated list of company names to use in Carrier-approved SMS templates.', size=None),
        ),
        migrations.AlterField(
            model_name='company',
            name='outgoing_user_names',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=16), blank=True, default=list, help_text='Comma seperated list of first names to use in Carrier-approved SMS templates.', size=None),
        ),
        migrations.AlterField(
            model_name='company',
            name='send_carrier_approved_templates',
            field=models.BooleanField(default=False, help_text='Allow campaigns to use carrier-approved SMS templates'),
        ),
        migrations.AlterField(
            model_name='invitationcode',
            name='code',
            field=models.CharField(blank=True, default='unknown', max_length=16, unique=True),
            preserve_default=False,
        ),
    ]
