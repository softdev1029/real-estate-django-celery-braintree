# Generated by Django 2.2.24 on 2021-08-02 20:12

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0181_auto_20210730_1617'),
        ('billing', '0008_auto_20210311_1400'),
    ]

    operations = [
        migrations.CreateModel(
            name='BTAddon',
            fields=[
                ('created_at', models.DateTimeField()),
                ('updated_at', models.DateTimeField()),
                ('id', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=64)),
                ('description', models.TextField()),
                ('amount', models.DecimalField(decimal_places=2, max_digits=8)),
                ('never_expires', models.BooleanField()),
                ('number_of_billing_cycles', models.PositiveIntegerField(null=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='BTDiscount',
            fields=[
                ('created_at', models.DateTimeField()),
                ('updated_at', models.DateTimeField()),
                ('id', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=64)),
                ('description', models.TextField()),
                ('amount', models.DecimalField(decimal_places=2, max_digits=8)),
                ('never_expires', models.BooleanField()),
                ('number_of_billing_cycles', models.PositiveIntegerField(null=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='BTTransaction',
            fields=[
                ('created_at', models.DateTimeField()),
                ('updated_at', models.DateTimeField()),
                ('id', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('customer_id', models.CharField(max_length=64)),
                ('refunded_transaction_id', models.CharField(max_length=64, null=True)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=8)),
                ('custom_type', models.CharField(max_length=32, null=True)),
                ('gateway_rejection_reason', models.CharField(max_length=32, null=True)),
                ('plan_id', models.CharField(max_length=32, null=True)),
                ('recurring', models.BooleanField(default=False)),
                ('t_type', models.CharField(max_length=32, null=True)),
                ('discount_amount', models.DecimalField(decimal_places=2, max_digits=8)),
                ('status', models.CharField(max_length=32)),
                ('first_name', models.CharField(max_length=64, null=True)),
                ('last_name', models.CharField(max_length=64, null=True)),
                ('street_address', models.CharField(max_length=128, null=True)),
                ('postal_code', models.CharField(max_length=5)),
                ('last_4', models.SmallIntegerField()),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='sherpa.Company')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='BTTransactionStatus',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(max_length=32)),
                ('timestamp', models.DateTimeField()),
                ('amount', models.DecimalField(decimal_places=2, max_digits=8)),
                ('source', models.CharField(max_length=32, null=True)),
                ('transaction_id', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='billing.BTTransaction')),
            ],
        ),
        migrations.CreateModel(
            name='BTPlan',
            fields=[
                ('created_at', models.DateTimeField()),
                ('updated_at', models.DateTimeField()),
                ('id', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=64)),
                ('description', models.TextField()),
                ('price', models.DecimalField(decimal_places=2, max_digits=8)),
                ('billing_day_of_month', models.PositiveSmallIntegerField(null=True)),
                ('billing_frequency', models.PositiveIntegerField()),
                ('number_of_billing_cycles', models.PositiveIntegerField(null=True)),
                ('trial_period', models.BooleanField()),
                ('trial_duration', models.PositiveIntegerField(null=True)),
                ('trial_duration_unit', models.CharField(max_length=16, null=True)),
                ('add_ons', models.ManyToManyField(to='billing.BTAddon')),
                ('discounts', models.ManyToManyField(to='billing.BTDiscount')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
