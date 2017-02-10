# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('life', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='forest',
            name='fork_of',
            field=models.ForeignKey(related_name='forks', on_delete=django.db.models.deletion.PROTECT, to='life.Forest', null=True),
        ),
        migrations.AddField(
            model_name='repository',
            name='fork_of',
            field=models.ForeignKey(related_name='forks', on_delete=django.db.models.deletion.PROTECT, to='life.Repository', null=True),
        ),
    ]
