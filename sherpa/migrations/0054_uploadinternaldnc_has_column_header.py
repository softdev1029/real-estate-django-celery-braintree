# Generated by Django 2.2.13 on 2020-06-17 22:43

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0053_auto_20200612_1554'),
    ]

    operations = [
        migrations.AddField(
            model_name='uploadinternaldnc',
            name='has_column_header',
            field=models.BooleanField(default=False),
        ),
    ]
