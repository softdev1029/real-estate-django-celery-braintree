# Generated by Django 2.2.13 on 2020-08-19 16:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0102_auto_20200818_2026'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='is_demo',
            field=models.BooleanField(default=False),
        ),
    ]
