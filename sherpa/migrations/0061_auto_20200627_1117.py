# Generated by Django 2.2.13 on 2020-06-27 11:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0060_auto_20200625_1254'),
    ]

    operations = [
        migrations.AlterField(
            model_name='prospect',
            name='has_unread_sms',
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]