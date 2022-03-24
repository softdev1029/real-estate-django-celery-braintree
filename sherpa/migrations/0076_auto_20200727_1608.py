# Generated by Django 2.2.13 on 2020-07-27 16:08

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0075_merge_20200727_1431'),
    ]

    operations = [
        migrations.AlterField(
            model_name='campaignprospect',
            name='count_as_unique',
            field=models.BooleanField(default=False, null=True),
        ),
        migrations.AlterField(
            model_name='campaignprospect',
            name='has_delivered_sms_only',
            field=models.BooleanField(default=False, null=True),
        ),
        migrations.AlterField(
            model_name='campaignprospect',
            name='has_responded2',
            field=models.BooleanField(default=False, null=True),
        ),
        migrations.AlterField(
            model_name='campaignprospect',
            name='has_responded_dead_auto2',
            field=models.BooleanField(default=False, null=True),
        ),
        migrations.AlterField(
            model_name='campaignprospect',
            name='is_associated_dnc',
            field=models.BooleanField(default=False, null=True),
        ),
        migrations.AlterField(
            model_name='campaignprospect',
            name='is_followup_cp',
            field=models.BooleanField(default=False, null=True),
        ),
        migrations.AlterField(
            model_name='campaignprospect',
            name='put_back_in_pool',
            field=models.BooleanField(default=False, null=True),
        ),
        migrations.AlterField(
            model_name='campaignprospect',
            name='send_sms',
            field=models.BooleanField(default=False, null=True),
        ),
        migrations.AlterField(
            model_name='campaignprospect',
            name='two_attempts_skip',
            field=models.BooleanField(default=False, null=True),
        ),
    ]