# Generated by Django 5.0.6 on 2024-06-19 18:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cb', '0023_searchresult_copy_number_searchresult_rank_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='analysisgroup',
            name='ptm',
        ),
        migrations.AddField(
            model_name='analysisgroup',
            name='analysis_group_type',
            field=models.CharField(choices=[('proteomics', 'Proteomics'), ('ptm', 'Post-translational Modification'), ('proteogenomics', 'Proteogenomics')], default='proteomics', max_length=255),
        ),
    ]
