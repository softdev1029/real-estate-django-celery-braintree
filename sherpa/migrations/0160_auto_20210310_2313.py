# Generated by Django 2.2.13 on 2021-03-10 23:13

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0159_merge_20210309_2013'),
    ]

    operations = [
        migrations.AlterField(
            model_name='campaign',
            name='market',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='sherpa.Market'),
        ),
    ]
