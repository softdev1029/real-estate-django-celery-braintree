# Generated by Django 2.2.13 on 2021-02-18 18:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0153_auto_20210215_1524'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='billing_address',
            field=models.TextField(default=''),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='company',
            name='city',
            field=models.CharField(default='', max_length=64),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='company',
            name='state',
            field=models.CharField(default='', max_length=32),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='company',
            name='zip_code',
            field=models.CharField(default='', max_length=16),
            preserve_default=False,
        ),
    ]
