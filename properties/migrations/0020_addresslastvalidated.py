# Generated by Django 2.2.13 on 2021-04-23 20:45

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('properties', '0019_auto_20210120_1531'),
    ]

    operations = [
        migrations.CreateModel(
            name='AddressLastValidated',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('property_id', models.IntegerField(blank=True, null=True)),
                ('last_checked', models.DateTimeField(auto_now=True)),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
