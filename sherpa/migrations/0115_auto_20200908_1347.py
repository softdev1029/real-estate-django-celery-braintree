# Generated by Django 2.2.13 on 2020-09-08 13:47

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0114_auto_20200908_1322'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='statsbatch',
            name='created_local',
        ),
        migrations.RemoveField(
            model_name='statsbatch',
            name='first_send_local',
        ),
        migrations.RemoveField(
            model_name='statsbatch',
            name='last_send_local',
        ),
        migrations.RemoveField(
            model_name='statsbatch',
            name='undelivered',
        ),
    ]
