# Generated by Django 2.2.10 on 2020-04-23 19:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0002_auto_20200307_1112'),
    ]

    operations = [
        migrations.RenameField(
            model_name='plan',
            old_name='max_phone_number_count',
            new_name='first_market_phone_number_count',
        ),
        migrations.AddField(
            model_name='plan',
            name='display',
            field=models.CharField(default='', max_length=16),
            preserve_default=False,
        ),
    ]