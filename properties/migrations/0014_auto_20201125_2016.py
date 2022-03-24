# Generated by Django 2.2.13 on 2020-11-25 20:16

from django.db import migrations


def create_quitclaim_flag(apps, schema_editor):
    Company = apps.get_model('sherpa', 'Company')
    PropertyTag = apps.get_model('properties', 'PropertyTag')
    for company in Company.objects.all():
        PropertyTag.objects.get_or_create(
            company=company,
            name='Quitclaim',
            distress_indicator=True,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('properties', '0013_property_upload_skip_trace'),
    ]

    operations = [
        migrations.RunPython(create_quitclaim_flag, migrations.RunPython.noop)
    ]
