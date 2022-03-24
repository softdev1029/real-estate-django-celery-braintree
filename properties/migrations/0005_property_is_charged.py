# Generated by Django 2.2.13 on 2020-10-23 15:07

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('properties', '0004_merge_20200916_1058'),
    ]

    operations = [
        migrations.AddField(
            model_name='property',
            name='is_charged',
            field=models.BooleanField(blank=True, help_text='Indicates Property has already been charged in a push to campaign.', null=True),
        ),
    ]