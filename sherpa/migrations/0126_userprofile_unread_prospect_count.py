# Generated by Django 2.2.13 on 2020-09-24 18:15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0125_auto_20200921_2023'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='unread_prospect_count',
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
