# Generated by Django 2.2.24 on 2021-08-20 20:45

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0009_btaddon_btdiscount_btplan_bttransaction_bttransactionstatus'),
    ]

    operations = [
        migrations.DeleteModel(
            name='Discrepancy',
        ),
    ]
