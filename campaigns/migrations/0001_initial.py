# Generated by Django 2.2.10 on 2020-03-07 11:12

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='CampaignFolder',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=128)),
                ('is_active', models.BooleanField(default=True)),
            ],
        ),
        migrations.CreateModel(
            name='CampaignIssue',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=16, unique=True)),
                ('issue_desc', models.CharField(max_length=255)),
                ('suggestions', django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=128), default=list, size=None)),
            ],
        ),
        migrations.CreateModel(
            name='CampaignNote',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_date', models.DateTimeField(auto_now_add=True)),
                ('text', models.TextField(blank=True, null=True)),
            ],
            options={
                'ordering': ('-created_date',),
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='CampaignTag',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=32)),
            ],
        ),
        migrations.CreateModel(
            name='InitialResponse',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('is_auto_dead', models.BooleanField(default=False)),
            ],
        ),
    ]
