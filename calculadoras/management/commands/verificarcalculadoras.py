from django.core.management.base import BaseCommand
from calculadoras.models import CalculadoraDivisa

class Command(BaseCommand):
    help = 'Verifica las calculadoras en la base de datos'

    def handle(self, *args, **options):
        calculadoras = CalculadoraDivisa.objects.all()
        self.stdout.write(f'Total de calculadoras: {calculadoras.count()}')
        for calc in calculadoras:
            self.stdout.write(f'ID: {calc.id}, Nombre: {calc.nombre}, '
                            f'Moneda origen: {calc.moneda_origen}, '
                            f'Moneda destino: {calc.moneda_destino}, '
                            f'Relación: {calc.relacion}, '
                            f'Activa: {calc.activa}')
