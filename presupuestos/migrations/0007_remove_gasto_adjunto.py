# Generated by Django 5.2.3 on 2025-07-07 16:03

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('presupuestos', '0006_alter_gasto_adjunto'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='gasto',
            name='adjunto',
        ),
    ]
