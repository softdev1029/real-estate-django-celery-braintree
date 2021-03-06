# Generated by Django 2.2.10 on 2020-03-07 11:12

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='CompanyChurn',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('days_until_subscription', models.SmallIntegerField(null=True)),
                ('prospect_upload_percent', models.DecimalField(decimal_places=3, max_digits=4, null=True)),
            ],
            options={
                'verbose_name_plural': 'Company churn',
            },
        ),
        migrations.CreateModel(
            name='CompanyGoal',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('budget', models.DecimalField(decimal_places=2, max_digits=13)),
                ('leads', models.IntegerField()),
                ('avg_response_time', models.IntegerField()),
                ('new_campaigns', models.IntegerField()),
                ('delivery_rate_percent', models.IntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ('-id',),
            },
        ),
    ]
