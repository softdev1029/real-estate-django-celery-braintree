# Generated by Django 2.2.12 on 2020-06-10 22:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sms', '0003_auto_20200513_1951'),
    ]

    operations = [
        migrations.AddField(
            model_name='carrierapprovedtemplate',
            name='alternate_message',
            field=models.TextField(blank=True, help_text='If not provided, will randomly select an alternate message from database.', max_length=300, null=True),
        ),
    ]
