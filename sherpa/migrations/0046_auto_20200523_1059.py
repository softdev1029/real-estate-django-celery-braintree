# Generated by Django 2.2.12 on 2020-05-23 10:59

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0045_merge_20200523_1048'),
    ]

    operations = [
        migrations.AlterField(
            model_name='uploadinternaldnc',
            name='status',
            field=models.CharField(choices=[('auto_stop', 'Auto Stop'), ('complete', 'Complete'), ('error', 'Error'), ('paused', 'Paused'), ('running', 'Running'), ('sent_to_task', 'Sent to Task'), ('setup', 'Setup')], default='setup', max_length=16),
        ),
        migrations.AlterField(
            model_name='uploadlitigatorcheck',
            name='status',
            field=models.CharField(choices=[('auto_stop', 'Auto Stop'), ('complete', 'Complete'), ('error', 'Error'), ('paused', 'Paused'), ('running', 'Running'), ('sent_to_task', 'Sent to Task'), ('setup', 'Setup')], default='setup', max_length=16),
        ),
        migrations.AlterField(
            model_name='uploadlitigatorlist',
            name='status',
            field=models.CharField(choices=[('auto_stop', 'Auto Stop'), ('complete', 'Complete'), ('error', 'Error'), ('paused', 'Paused'), ('running', 'Running'), ('sent_to_task', 'Sent to Task'), ('setup', 'Setup')], default='setup', max_length=16),
        ),
        migrations.AlterField(
            model_name='uploadprospects',
            name='status',
            field=models.CharField(choices=[('auto_stop', 'Auto Stop'), ('complete', 'Complete'), ('error', 'Error'), ('paused', 'Paused'), ('running', 'Running'), ('sent_to_task', 'Sent to Task'), ('setup', 'Setup')], default='setup', max_length=16),
        ),
        migrations.AlterField(
            model_name='uploadskiptrace',
            name='status',
            field=models.CharField(choices=[('auto_stop', 'Auto Stop'), ('complete', 'Complete'), ('error', 'Error'), ('paused', 'Paused'), ('running', 'Running'), ('sent_to_task', 'Sent to Task'), ('setup', 'Setup')], default='setup', max_length=16),
        ),
    ]
