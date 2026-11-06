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
            aporte_mensual_prestamo=Decimal('600000.00'),
            deuda_inicial_prestamo=Decimal('10129746.00')
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

    def test_caso_real_usuario_ciclo_devolucion(self):
        # El usuario devuelve 10.129.746 sacando 9.529.746 con tarjetas y poniendo 600.000 en efectivo
        tarjetas = Ingreso.objects.create(
            presupuesto=self.presupuesto,
            nombre='Tarjetas sacadas ciclo',
            monto=Decimal('9529746.00'),
            es_extraccion_tarjeta=True,
            tasa_interes=Decimal('4.50'),
            monto_proximo_mes=round(Decimal('9529746.00') * Decimal('1.045'), 2)
        )
        efectivo = Ingreso.objects.create(
            presupuesto=self.presupuesto,
            nombre='Aporte en efectivo',
            monto=Decimal('600000.00'),
            es_aporte_capital=True
        )

        # Efectivo no tiene interés
        self.assertEqual(efectivo.interes_monto, 0)
        # Tarjetas tienen interés 4.5%
        self.assertEqual(tarjetas.interes_monto, round(Decimal('9529746.00') * Decimal('0.045'), 2))

        # Total devuelto este mes
        total_devuelto = tarjetas.monto + efectivo.monto
        self.assertEqual(total_devuelto, Decimal('10129746.00'))

        # Deuda para el mes siguiente: solo las tarjetas con 4.5%
        deuda_proximo_mes = tarjetas.monto_proximo_mes
        self.assertEqual(deuda_proximo_mes, Decimal('9958584.57'))

        # Con el aporte del mes que viene (600k), solo necesitará sacar 9.358.584,57 con tarjeta
        tarjeta_necesaria_sig = deuda_proximo_mes - self.presupuesto.aporte_mensual_prestamo
        self.assertEqual(tarjeta_necesaria_sig, Decimal('9358584.57'))
