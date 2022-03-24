# Generated by Django 2.2.10 on 2020-04-29 16:40

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0035_auto_20200424_2109'),
        ('campaigns', '0004_remove_campaignfolder_is_active'),
    ]

    operations = [
        migrations.CreateModel(
            name='CampaignDailyStats',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(db_index=True)),
                ('new_leads', models.PositiveSmallIntegerField()),
                ('skipped', models.PositiveSmallIntegerField()),
                ('delivered', models.PositiveSmallIntegerField()),
                ('sent', models.PositiveSmallIntegerField()),
                ('auto_dead', models.PositiveSmallIntegerField()),
                ('responses', models.PositiveSmallIntegerField()),
                ('campaign', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='sherpa.Campaign')),
            ],
            options={
                'unique_together': {('campaign', 'date')},
            },
        ),
    ]
