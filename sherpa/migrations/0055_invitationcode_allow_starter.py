# Generated by Django 2.2.13 on 2020-06-19 19:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0054_uploadinternaldnc_has_column_header'),
    ]

    operations = [
        migrations.AddField(
            model_name='invitationcode',
            name='allow_starter',
            field=models.BooleanField(default=False),
        ),
    ]
