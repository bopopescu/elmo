# -*- coding: utf-8 -*-
# Generated by Django 1.11.15 on 2018-09-11 08:27
from __future__ import absolute_import
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tinder', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='mastermap',
            name='master',
        ),
        migrations.RemoveField(
            model_name='mastermap',
            name='webhead',
        ),
        migrations.RemoveField(
            model_name='webhead',
            name='masters',
        ),
        migrations.DeleteModel(
            name='MasterMap',
        ),
        migrations.DeleteModel(
            name='WebHead',
        ),
    ]