# Generated by Django 2.2.12 on 2020-05-28 19:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0048_merge_20200526_1700'),
    ]

    operations = [
        migrations.AlterField(
            model_name='uploadprospects',
            name='exceeds_count',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
