# Generated by Django 2.2.10 on 2020-03-20 18:52

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0010_auto_20200318_1044'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='created',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
    ]