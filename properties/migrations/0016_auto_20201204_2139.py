# Generated by Django 2.2.13 on 2020-12-04 21:39

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('properties', '0015_merge_20201127_0529'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='propertytagassignment',
            unique_together={('tag', 'prop')},
        ),
    ]
