# Generated by Django 5.0.6 on 2024-06-19 18:52

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cb', '0024_remove_analysisgroup_ptm_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='analysisgroup',
            name='analysis_group_type',
            field=models.CharField(choices=[('proteomics', 'Proteomics'), ('ptm', 'Post-translational Modification'), ('proteogenomics', 'Proteogenomics'), ('metabolomics', 'Metabolomics'), ('lipidomics', 'Lipidomics'), ('glycomics', 'Glycomics'), ('glycoproteomics', 'Glycoproteomics')], default='proteomics', max_length=255),
        ),
    ]
