# Generated by Django 2.2.13 on 2021-04-01 22:51

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0160_auto_20210325_1632'),
    ]

    operations = [
        migrations.AlterField(
            model_name='company',
            name='allow_smart_stacker',
            field=models.BooleanField(default=True, help_text='Determines if the company can view Smart Stacker.'),
        ),
    ]
