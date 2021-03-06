# Generated by Django 2.2.13 on 2021-04-06 18:29

from django.db import migrations, models

def turn_on_telnyx(apps, schema_editor):
    Company = apps.get_model('sherpa', 'Company')
    for company in Company.objects.all():
        if company.market_set.exclude(name='Twilio').count() > 0:
            company.allow_telnyx_add_on = True
            company.save(update_fields=['allow_telnyx_add_on'])

class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0168_merge_20210405_2148'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='allow_telnyx_add_on',
            field=models.BooleanField(default=False),
        ),

        migrations.RunPython(turn_on_telnyx),
    ]
