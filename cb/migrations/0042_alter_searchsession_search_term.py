# Generated by Django 5.1.5 on 2025-01-17 11:26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cb', '0041_metadatacolumn_mandatory'),
    ]

    operations = [
        migrations.AlterField(
            model_name='searchsession',
            name='search_term',
            field=models.TextField(),
        ),
    ]