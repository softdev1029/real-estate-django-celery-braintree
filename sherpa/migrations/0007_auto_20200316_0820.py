# Generated by Django 2.2.10 on 2020-03-16 08:20

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0006_auto_20200302_1415'),
    ]

    operations = [
        migrations.AddField(
            model_name='invitationcode',
            name='discount_code',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='invitationcode',
            name='option_1_discount_code',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='invitationcode',
            name='option_2_discount_code',
            field=models.CharField(blank=True, max_length=32),
        ),
    ]
