# Generated by Django 2.2.13 on 2020-08-04 15:39

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0080_merge_20200804_1434'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='record_calls',
            field=models.BooleanField(default=False, help_text='Determines if calls should be recorded.'),
        ),
    ]
