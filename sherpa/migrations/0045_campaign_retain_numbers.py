# Generated by Django 2.2.12 on 2020-05-22 20:47

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0044_auto_20200522_1352'),
    ]

    operations = [
        migrations.AddField(
            model_name='campaign',
            name='retain_numbers',
            field=models.BooleanField(default=False),
        ),
    ]
