# Generated by Django 2.2.13 on 2021-02-18 15:55

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0151_company_enable_crm_integration'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='invite_code',
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
    ]
