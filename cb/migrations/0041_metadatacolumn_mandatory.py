# Generated by Django 5.1.3 on 2024-11-13 17:06

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cb', '0040_metadatacolumn_not_applicable'),
    ]

    operations = [
        migrations.AddField(
            model_name='metadatacolumn',
            name='mandatory',
            field=models.BooleanField(default=False),
        ),
    ]
