# Generated by Django 5.0.6 on 2024-11-12 16:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cb', '0039_msuniquevocabularies_unimod'),
    ]

    operations = [
        migrations.AddField(
            model_name='metadatacolumn',
            name='not_applicable',
            field=models.BooleanField(default=False),
        ),
    ]