# Generated by Django 2.2.13 on 2020-07-09 14:04

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0067_merge_20200709_1335'),
    ]

    operations = [
        migrations.AddField(
            model_name='prospect',
            name='reminder_agent',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reminder_agent', to='sherpa.UserProfile'),
        ),
    ]
