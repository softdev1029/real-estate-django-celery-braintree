# Generated by Django 2.2.13 on 2021-04-26 21:13

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0173_featurenotification_userfeaturenotification'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='company',
            name='allow_direct_mail',
        ),
        migrations.RemoveField(
            model_name='company',
            name='allow_smart_stacker',
        ),
        migrations.RemoveField(
            model_name='company',
            name='enable_crm_integration',
        ),
    ]
