# Generated by Django 5.0.6 on 2024-09-25 11:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cb', '0033_collate_users'),
    ]

    operations = [
        migrations.AddField(
            model_name='searchresult',
            name='ptm_data',
            field=models.TextField(blank=True, null=True),
        ),
    ]
