# Generated by Django 2.2.10 on 2020-04-22 17:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0032_merge_20200421_2047'),
    ]

    operations = [
        migrations.AlterField(
            model_name='phonenumber',
            name='provider_id',
            field=models.CharField(blank=True, max_length=125),
        ),
    ]
