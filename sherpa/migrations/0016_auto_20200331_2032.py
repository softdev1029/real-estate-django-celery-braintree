# Generated by Django 2.2.10 on 2020-03-31 20:32

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0015_auto_20200330_1447'),
    ]

    operations = [
        migrations.AlterField(
            model_name='skiptraceproperty',
            name='age',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
