# Generated by Django 2.2.13 on 2020-08-11 11:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0091_auto_20200808_1218'),
    ]

    operations = [
        migrations.AlterField(
            model_name='campaignprospect',
            name='put_back_in_pool',
            field=models.BooleanField(null=True),
        ),
        migrations.AlterField(
            model_name='campaignprospect',
            name='two_attempts_skip',
            field=models.BooleanField(null=True),
        ),
    ]
