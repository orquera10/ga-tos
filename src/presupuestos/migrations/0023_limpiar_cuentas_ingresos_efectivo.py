from django.db import migrations

def limpiar_cuentas_efectivo(apps, schema_editor):
    Ingreso = apps.get_model('presupuestos', 'Ingreso')
    Ingreso.objects.filter(tipo_ingreso='efectivo').update(cuenta_bancaria=None)

class Migration(migrations.Migration):

    dependencies = [
        ('presupuestos', '0022_diferenciatarjeta'),
    ]

    operations = [
        migrations.RunPython(limpiar_cuentas_efectivo, migrations.RunPython.noop),
    ]
