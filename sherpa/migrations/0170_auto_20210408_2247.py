# Generated by Django 2.2.13 on 2021-04-08 22:31

from django.db import migrations, models

def populate_features(apps, schema_editor):
    """
    Populate features
    """
    Features = apps.get_model("sherpa", "Features")
    choices = [
        'texting',
        'skip_trace',
        'list_stacking',
        'direct_mail',
    ]
    for choice in choices:
        Features.objects.create(name=choice)

class Migration(migrations.Migration):

    dependencies = [
        ('sherpa', '0169_company_allow_telnyx_add_on'),
    ]

    operations = [
        migrations.CreateModel(
            name='Features',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(choices=[('texting', 'Texting'), ('skip_trace', 'Skip Trace'), ('list_stacking', 'List Stacking'), ('direct_mail', 'Direct Mail')], max_length=20, unique=True)),
            ],
        ),
        migrations.AddField(
            model_name='userprofile',
            name='interesting_features',
            field=models.ManyToManyField(to='sherpa.Features'),
        ),

        migrations.RunPython(populate_features, migrations.RunPython.noop)
    ]
