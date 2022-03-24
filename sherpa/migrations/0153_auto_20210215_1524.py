# Generated by Django 2.2.13 on 2021-02-15 15:24

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0152_auto_20210211_1405'),
    ]

    operations = [
        migrations.AlterField(
            model_name='uploadinternaldnc',
            name='status',
            field=models.CharField(choices=[('auto_stop', 'Auto Stop'), ('complete', 'Complete'), ('error', 'Error'), ('cancelled', 'Cancelled'), ('paused', 'Paused'), ('running', 'Running'), ('sent_to_task', 'Sent to Task'), ('setup', 'Setup')], default='setup', max_length=16),
        ),
        migrations.AlterField(
            model_name='uploadlitigatorcheck',
            name='status',
            field=models.CharField(choices=[('auto_stop', 'Auto Stop'), ('complete', 'Complete'), ('error', 'Error'), ('cancelled', 'Cancelled'), ('paused', 'Paused'), ('running', 'Running'), ('sent_to_task', 'Sent to Task'), ('setup', 'Setup')], default='setup', max_length=16),
        ),
        migrations.AlterField(
            model_name='uploadlitigatorlist',
            name='status',
            field=models.CharField(choices=[('auto_stop', 'Auto Stop'), ('complete', 'Complete'), ('error', 'Error'), ('cancelled', 'Cancelled'), ('paused', 'Paused'), ('running', 'Running'), ('sent_to_task', 'Sent to Task'), ('setup', 'Setup')], default='setup', max_length=16),
        ),
        migrations.AlterField(
            model_name='uploadprospects',
            name='status',
            field=models.CharField(choices=[('auto_stop', 'Auto Stop'), ('complete', 'Complete'), ('error', 'Error'), ('cancelled', 'Cancelled'), ('paused', 'Paused'), ('running', 'Running'), ('sent_to_task', 'Sent to Task'), ('setup', 'Setup')], default='setup', max_length=16),
        ),
        migrations.AlterField(
            model_name='uploadskiptrace',
            name='status',
            field=models.CharField(choices=[('auto_stop', 'Auto Stop'), ('complete', 'Complete'), ('error', 'Error'), ('cancelled', 'Cancelled'), ('paused', 'Paused'), ('running', 'Running'), ('sent_to_task', 'Sent to Task'), ('setup', 'Setup')], default='setup', max_length=16),
        ),
    ]
