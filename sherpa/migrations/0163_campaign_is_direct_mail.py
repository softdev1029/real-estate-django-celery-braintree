# Generated by Django 2.2.13 on 2021-03-15 21:41

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0162_merge_20210315_2128'),
    ]

    operations = [
        migrations.AddField(
            model_name='campaign',
            name='is_direct_mail',
            field=models.BooleanField(default=False),
        ),
    ]
