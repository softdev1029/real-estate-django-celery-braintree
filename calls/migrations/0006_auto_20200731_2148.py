# Generated by Django 2.2.13 on 2020-07-31 21:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calls', '0005_auto_20200723_1520'),
    ]

    operations = [
        migrations.AlterField(
            model_name='call',
            name='recording',
            field=models.URLField(blank=True, max_length=500, null=True),
        ),
    ]