# Generated by Django 2.2.10 on 2020-03-07 11:12

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('sherpa', '0001_initial'),
        ('campaigns', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='initialresponse',
            name='campaign',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='sherpa.Campaign'),
        ),
        migrations.AddField(
            model_name='initialresponse',
            name='message',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='sherpa.SMSMessage'),
        ),
        migrations.AddField(
            model_name='campaigntag',
            name='company',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='sherpa.Company'),
        ),
        migrations.AddField(
            model_name='campaignnote',
            name='campaign',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notes', to='sherpa.Campaign'),
        ),
        migrations.AddField(
            model_name='campaignnote',
            name='created_by',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='campaignfolder',
            name='company',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='sherpa.Company'),
        ),
        migrations.AlterUniqueTogether(
            name='initialresponse',
            unique_together={('campaign', 'message')},
        ),
        migrations.AlterUniqueTogether(
            name='campaigntag',
            unique_together={('company', 'name')},
        ),
    ]
