# Generated by Django 2.2.13 on 2021-05-26 19:21

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0176_uploadskiptrace_push_to_campaign_stage'),
    ]

    operations = [
        migrations.AlterField(
            model_name='uploadskiptrace',
            name='push_to_campaign_status',
            field=models.CharField(choices=[('open', 'Open'), ('queued', 'Queued'), ('running', 'Running'), ('error', 'Error'), ('auto_stop', 'Stopped'), ('complete', 'Complete'), ('paused', 'Paused')], default='open', max_length=255),
        ),
    ]
