# Generated by Django 5.0.6 on 2024-06-16 18:13

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cb', '0017_rename_foldchange_searchresult_log10_p_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='searchsession',
            name='failed',
            field=models.BooleanField(default=False),
        ),
    ]
