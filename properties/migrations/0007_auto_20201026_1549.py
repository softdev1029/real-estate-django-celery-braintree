# Generated by Django 2.2.13 on 2020-10-26 15:49

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('properties', '0006_auto_20201026_1516'),
    ]

    operations = [
        migrations.AlterField(
            model_name='attomamortizedloanequitymodel',
            name='first_loan_amortized',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=20, null=True),
        ),
        migrations.AlterField(
            model_name='attomamortizedloanequitymodel',
            name='first_loan_transaction_id',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='attomamortizedloanequitymodel',
            name='second_loan_amortized',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=20, null=True),
        ),
        migrations.AlterField(
            model_name='attomamortizedloanequitymodel',
            name='second_loan_transaction_id',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='attomamortizedloanequitymodel',
            name='third_loan_amortized',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=20, null=True),
        ),
        migrations.AlterField(
            model_name='attomamortizedloanequitymodel',
            name='third_loan_transaction_id',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
