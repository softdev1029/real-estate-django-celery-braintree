# Generated by Django 2.2.10 on 2020-03-30 14:47

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0014_company_block_unknown_calls'),
    ]

    operations = [
        migrations.AlterField(
            model_name='company',
            name='block_unknown_calls',
            field=models.BooleanField(default=True, help_text='Only allow calls from known prospects to be forwarded.'),
        ),
        migrations.AlterField(
            model_name='company',
            name='threshold_days',
            field=models.PositiveSmallIntegerField(default=5, help_text="Day amount that the company can't resend bulk messages to prospects for."),
        ),
        migrations.AlterField(
            model_name='company',
            name='threshold_exempt',
            field=models.BooleanField(default=False, help_text='Allow users to send bulk messages bypassing the day check rule.'),
        ),
    ]
