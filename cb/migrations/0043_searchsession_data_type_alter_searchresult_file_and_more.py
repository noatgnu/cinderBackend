# Generated by Django 5.1.5 on 2025-01-24 16:33

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cb', '0042_alter_searchsession_search_term'),
    ]

    operations = [
        migrations.AddField(
            model_name='searchsession',
            name='data_type',
            field=models.CharField(blank=True, choices=[('proteomics', 'Proteomics'), ('ptm', 'Post-translational Modification'), ('proteogenomics', 'Proteogenomics'), ('metabolomics', 'Metabolomics'), ('lipidomics', 'Lipidomics'), ('glycomics', 'Glycomics'), ('glycoproteomics', 'Glycoproteomics')], default='proteomics', max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='searchresult',
            name='file',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='search_results', to='cb.projectfile'),
        ),
        migrations.AlterField(
            model_name='searchsession',
            name='species',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='search_sessions', to='cb.species'),
        ),
    ]
