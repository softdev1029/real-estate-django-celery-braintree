# Generated by Django 2.2.10 on 2020-04-17 19:24

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0030_auto_20200420_1515'),
    ]

    operations = [
        migrations.AlterField(
            model_name='activity',
            name='title',
            field=models.CharField(choices=[('Added to DNC', 'Added to DNC'), ('Removed from DNC', 'Removed from DNC'), ('Owner Not Valid', 'Owner Not Valid'), ('Owner Verified', 'Owner Verified'), ('Owner Unverified', 'Owner Unverified'), ('Added as Priority', 'Added as Priority'), ('Removed as Priority', 'Removed as Priority'), ('Qualified Lead Added', 'Qualified Lead Added'), ('Qualified Lead Removed', 'Qualified Lead Removed'), ('Added Autodead', 'Added Autodead'), ('Removed Autodead', 'Removed Autodead'), ('Created Note', 'Created Note'), ('Added Wrong Number', 'Added Wrong Number'), ('Removed Wrong Number', 'Removed Wrong Number')], max_length=255),
        ),
        migrations.AddField(
            model_name='campaign',
            name='total_wrong_number_count',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='statsbatch',
            name='skipped_wrong_number',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='campaignprospect',
            name='skip_reason',
            field=models.CharField(blank=True, choices=[('threshold', 'Threshold'), ('has_responded', 'Has responded previously'), ('company_dnc', 'Company DNC'), ('public_dnc', 'Public DNC'), ('litigator', 'Litigator'), ('has_receipt', 'Has SMS Receipt'), ('forced', 'Forced'), ('opt_out_required', 'Opt-out required'), ('carrier_att', 'AT&T'), ('outgoing_not_set', 'Outgoing not set'), ('wrong_number', 'Wrong number')], max_length=16),
        ),
    ]
