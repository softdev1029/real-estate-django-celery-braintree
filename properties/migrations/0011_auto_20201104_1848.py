# Generated by Django 2.2.13 on 2020-11-04 18:48

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('properties', '0010_auto_20201031_1146'),
    ]

    operations = [
        migrations.AlterField(
            model_name='address',
            name='attom',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='properties.AttomAssessor'),
        ),
    ]