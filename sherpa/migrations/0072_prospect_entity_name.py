# Generated by Django 2.2.12 on 2020-07-21 20:40

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0071_merge_20200721_1812'),
    ]

    operations = [
        migrations.AddField(
            model_name='prospect',
            name='entity_name',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
