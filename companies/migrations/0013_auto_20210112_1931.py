# Generated by Django 2.2.13 on 2021-01-12 19:31

from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0012_telephonyconnection'),
    ]

    operations = [
        migrations.AlterField(
            model_name='telephonyconnection',
            name='random_key',
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
    ]
