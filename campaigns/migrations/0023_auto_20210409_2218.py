# Generated by Django 2.2.13 on 2021-04-09 22:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0022_auto_20210401_2010'),
    ]

    operations = [
        migrations.AlterField(
            model_name='directmailorder',
            name='status',
            field=models.CharField(blank=True, choices=[('scheduled', 'scheduled'), ('processing', 'processing'), ('in_production', 'in_production'), ('production_complete', 'production_complete'), ('complete', 'complete'), ('out_for_delivery', 'out_for_delivery'), ('failed', 'failed'), ('locked', 'locked'), ('incomplete', 'incomplete'), ('cancelled', 'cancelled')], default='scheduled', max_length=255, null=True),
        ),
    ]
