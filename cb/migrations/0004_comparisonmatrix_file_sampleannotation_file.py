# Generated by Django 5.0.6 on 2024-06-11 19:57

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cb', '0003_alter_project_encrypted'),
    ]

    operations = [
        migrations.AddField(
            model_name='comparisonmatrix',
            name='file',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='comparison_matrices', to='cb.projectfile'),
        ),
        migrations.AddField(
            model_name='sampleannotation',
            name='file',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='sample_annotations', to='cb.projectfile'),
        ),
    ]
