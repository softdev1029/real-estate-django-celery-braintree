# Generated by Django 2.2.10 on 2020-04-02 12:27

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0017_auto_20200402_1643'),
    ]

    operations = [
        migrations.AddField(
            model_name='prospect',
            name='cloned_from',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='sherpa.Prospect'),
        ),
    ]
