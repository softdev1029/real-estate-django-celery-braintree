# Generated by Django 2.2.13 on 2020-08-05 22:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0086_auto_20200805_2154'),
    ]

    operations = [
        migrations.AddField(
            model_name='activity',
            name='related_lookup',
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True),
        ),
    ]
