# Generated by Django 2.2.10 on 2020-04-08 11:51

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0021_remove_uploadskiptrace_created_local'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='company',
            name='is_test_company',
        ),
        migrations.RemoveField(
            model_name='company',
            name='testing',
        ),
    ]