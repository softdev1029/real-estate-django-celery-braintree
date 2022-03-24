# Generated by Django 2.2.13 on 2020-10-19 16:28

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0134_merge_20201017_1402'),
    ]

    operations = [
        migrations.AddField(
            model_name='phonetype',
            name='last_carrier_lookup',
            field=models.DateField(blank=True, help_text='Date when this phones carrier was last checked against Telnyx.', null=True),
        ),
    ]
