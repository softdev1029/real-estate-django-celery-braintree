# Generated by Django 2.2.10 on 2020-03-25 13:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0012_auto_20200322_1221'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='is_primary',
            field=models.BooleanField(default=False),
        )
    ]
