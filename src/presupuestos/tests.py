from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from .models import Presupuesto, Ingreso

User = get_user_model()

class PrestamoTarjetasTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password123')
        self.presupuesto = Presupuesto.objects.create(
            usuario=self.user,
            nombre='Préstamo Tarjetas',
            tipo='prestamo',
            fecha_inicio=timezone.now().date(),
            fecha_fin=timezone.now().date() + timezone.timedelta(days=365),
            tasa_interes_prestamo=Decimal('4.50'),
            aporte_mensual_prestamo=Decimal('600000.00')
        )

    def test_suma_tarjetas_calcula_deuda_proximo_mes(self):
        # Tarjeta Patagonia: 1.500.000 -> 1.567.500
        pata = Ingreso.objects.create(
            presupuesto=self.presupuesto,
            nombre='Tarjeta Patagonia',
            monto=Decimal('1500000.00'),
            es_extraccion_tarjeta=True,
            tasa_interes=Decimal('4.50'),
            monto_proximo_mes=Decimal('1567500.00')
        )
        # Patagonia Palmira: 4.000.000 -> 4.180.000
        palm = Ingreso.objects.create(
            presupuesto=self.presupuesto,
            nombre='Tarjeta Patagonia Palmira',
            monto=Decimal('4000000.00'),
            es_extraccion_tarjeta=True,
            tasa_interes=Decimal('4.50'),
            monto_proximo_mes=Decimal('4180000.00')
        )
        # Tarjeta Naranja: 3.000.000 -> 3.135.000
        naranja = Ingreso.objects.create(
            presupuesto=self.presupuesto,
            nombre='Tarjeta Naranja',
            monto=Decimal('3000000.00'),
            es_extraccion_tarjeta=True,
            tasa_interes=Decimal('4.50'),
            monto_proximo_mes=Decimal('3135000.00')
        )

        self.assertEqual(pata.interes_monto, Decimal('67500.00'))
        self.assertEqual(palm.interes_monto, Decimal('180000.00'))
        self.assertEqual(naranja.interes_monto, Decimal('135000.00'))

        # Proyección toma la suma de las 3 tarjetas como deuda base
        proy = self.presupuesto.proyeccion_prestamo()
        self.assertIsNotNone(proy)
        self.assertEqual(proy['deuda_actual'], 8882500.00)
        self.assertTrue(proy['total_meses'] > 0)
