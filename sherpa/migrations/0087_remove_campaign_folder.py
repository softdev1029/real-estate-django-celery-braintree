# Generated by Django 2.2.13 on 2020-08-06 14:00

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0086_merge_20200805_1151'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='campaign',
            name='folder',
        ),
    ]