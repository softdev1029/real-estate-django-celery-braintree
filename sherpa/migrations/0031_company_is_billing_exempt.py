# Generated by Django 2.2.10 on 2020-04-21 17:21

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0030_auto_20200420_1515'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='is_billing_exempt',
            field=models.BooleanField(default=False),
        ),
    ]
