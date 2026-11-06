import json
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from presupuestos.models import Presupuesto, Categoria, Gasto
from .models import ApiToken


class ApiEndpointsTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='Password123!'
        )
        self.token = ApiToken.objects.create(user=self.user)
        self.auth_headers = {'HTTP_AUTHORIZATION': f'Bearer {self.token.token}'}

        self.presupuesto = Presupuesto.objects.create(
            usuario=self.user,
            nombre='Presupuesto Test',
            monto_total=Decimal('10000.00'),
            monto_restante=Decimal('10000.00'),
            fecha_inicio=timezone.localdate(),
            fecha_fin=timezone.localdate() + timezone.timedelta(days=30),
            moneda='ARS'
        )
        self.categoria = Categoria.objects.create(
            nombre='Supermercado',
            descripcion='Comida y despensa'
        )

    def test_login_success(self):
        resp = self.client.post(
            '/api/auth/login/',
            data=json.dumps({'username': 'testuser', 'password': 'Password123!'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertTrue('token' in data)

    def test_login_by_email_success(self):
        resp = self.client.post(
            '/api/auth/login/',
            data=json.dumps({'email': 'test@example.com', 'password': 'Password123!'}),
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])

    def test_presupuestos_api(self):
        resp = self.client.get('/api/presupuestos/', **self.auth_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['presupuestos']), 1)
        self.assertEqual(data['presupuestos'][0]['nombre'], 'Presupuesto Test')

    def test_categorias_api(self):
        resp = self.client.get('/api/categorias/', **self.auth_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertTrue(len(data['categorias']) >= 1)

    def test_crear_gasto_api(self):
        payload = {
            'presupuesto_id': self.presupuesto.id,
            'categoria_id': self.categoria.id,
            'nombre': 'Compra semanal',
            'monto': 1500.50,
            'descripcion': 'Frutas y verduras'
        }
        resp = self.client.post(
            '/api/gastos/crear/',
            data=json.dumps(payload),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['gasto']['nombre'], 'Compra semanal')
        self.assertEqual(data['presupuesto']['monto_restante'], 8499.50)

    def test_widget_resumen_api(self):
        # Crear un gasto primero
        Gasto.objects.create(
            presupuesto=self.presupuesto,
            categoria=self.categoria,
            nombre='Café',
            monto=Decimal('500.00')
        )
        resp = self.client.get(
            f'/api/widget/resumen/?presupuesto_id={self.presupuesto.id}',
            **self.auth_headers
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertIsNotNone(data['presupuesto'])
        self.assertEqual(len(data['ultimos_gastos']), 1)
        self.assertEqual(data['ultimos_gastos'][0]['nombre'], 'Café')

    def test_gasto_tarjeta_no_descuenta_saldo(self):
        payload = {
            'presupuesto_id': self.presupuesto.id,
            'nombre': 'Zapatillas cuotas',
            'monto': 3000.00,
            'metodo_pago': 'tarjeta'
        }
        resp = self.client.post(
            '/api/gastos/crear/',
            data=json.dumps(payload),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data['presupuesto']['monto_restante'], 10000.00)

        resp_resumen = self.client.get(
            f'/api/widget/resumen/?presupuesto_id={self.presupuesto.id}',
            **self.auth_headers
        )
        res_data = resp_resumen.json()
        self.assertEqual(res_data['presupuesto']['total_tarjeta'], 3000.00)

    def test_presupuesto_abierto(self):
        p_abierto = Presupuesto.objects.create(
            usuario=self.user,
            nombre='Flujo Continuo',
            tipo='abierto',
            monto_total=Decimal('0.00'),
            monto_restante=Decimal('0.00'),
            fecha_inicio=timezone.localdate(),
            fecha_fin=timezone.localdate() + timezone.timedelta(days=30),
            moneda='ARS'
        )
        self.client.post(
            '/api/ingresos/crear/',
            data=json.dumps({'presupuesto_id': p_abierto.id, 'nombre': 'Sueldo Mayo', 'monto': 80000.00, 'tipo_ingreso': 'sueldo'}),
            content_type='application/json',
            **self.auth_headers
        )
        self.client.post(
            '/api/gastos/crear/',
            data=json.dumps({'presupuesto_id': p_abierto.id, 'nombre': 'Supermercado', 'monto': 20000.00, 'metodo_pago': 'efectivo'}),
            content_type='application/json',
            **self.auth_headers
        )
        p_abierto.refresh_from_db()
        self.assertEqual(p_abierto.monto_restante, Decimal('60000.00'))

    def test_presupuesto_prestamo_excluido_de_widget(self):
        p_prestamo = Presupuesto.objects.create(
            usuario=self.user,
            nombre='Préstamo Auto',
            tipo='prestamo',
            monto_total=Decimal('0.00'),
            monto_restante=Decimal('0.00'),
            fecha_inicio=timezone.localdate(),
            fecha_fin=timezone.localdate() + timezone.timedelta(days=365),
            moneda='ARS'
        )
        # Verificar que funciona como flujo abierto
        self.client.post(
            '/api/ingresos/crear/',
            data=json.dumps({'presupuesto_id': p_prestamo.id, 'nombre': 'Desembolso Préstamo', 'monto': 500000.00, 'tipo_ingreso': 'transferencia'}),
            content_type='application/json',
            **self.auth_headers
        )
        self.client.post(
            '/api/gastos/crear/',
            data=json.dumps({'presupuesto_id': p_prestamo.id, 'nombre': 'Pago Cuota 1', 'monto': 50000.00, 'metodo_pago': 'transferencia'}),
            content_type='application/json',
            **self.auth_headers
        )
        p_prestamo.refresh_from_db()
        self.assertEqual(p_prestamo.monto_restante, Decimal('450000.00'))

        # Verificar que no aparece en /api/presupuestos/ para el widget
        resp_list = self.client.get('/api/presupuestos/', **self.auth_headers)
        data_list = resp_list.json()
        ids = [p['id'] for p in data_list['presupuestos']]
        self.assertNotIn(p_prestamo.id, ids)

        # Verificar que widget_resumen_api no auto-selecciona el préstamo
        resp_widget = self.client.get('/api/widget/resumen/', **self.auth_headers)
        data_widget = resp_widget.json()
        if data_widget.get('presupuesto'):
            self.assertNotEqual(data_widget['presupuesto']['tipo'], 'prestamo')

    def test_gasto_con_persona_y_cuenta_bancaria(self):
        resp_ing = self.client.post(
            '/api/ingresos/crear/',
            data=json.dumps({
                'presupuesto_id': self.presupuesto.id,
                'nombre': 'Cobro DiDi',
                'monto': 50000.00,
                'tipo_ingreso': 'transferencia',
                'cuenta_bancaria': 'Brubank'
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_ing.status_code, 201)
        self.assertEqual(resp_ing.json()['ingreso']['cuenta_bancaria'], 'Brubank')

        resp_gasto = self.client.post(
            '/api/gastos/crear/',
            data=json.dumps({
                'presupuesto_id': self.presupuesto.id,
                'nombre': 'Cena',
                'monto': 15000.00,
                'metodo_pago': 'transferencia',
                'persona': 'Victoria',
                'cuenta_bancaria': 'Brubank'
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_gasto.status_code, 201)
        self.assertEqual(resp_gasto.json()['gasto']['persona'], 'Victoria')
        self.assertEqual(resp_gasto.json()['gasto']['cuenta_bancaria'], 'Brubank')
