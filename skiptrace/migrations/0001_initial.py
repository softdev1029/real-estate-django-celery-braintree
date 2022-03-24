# Generated by Django 2.2.13 on 2020-10-16 12:06

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='SkipTraceDailyStats',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(unique=True)),
                ('total_external_hits', models.PositiveIntegerField()),
                ('total_internal_hits', models.PositiveIntegerField()),
            ],
            options={'verbose_name_plural': 'Skip trace daily stats'},
        ),
    ]
