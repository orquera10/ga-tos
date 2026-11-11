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

    def test_crear_cuenta_y_transferencia_y_detalle_app(self):
        # 1. Crear una cuenta nueva desde la pestaña Cuentas
        resp_cta = self.client.post(
            '/api/cuentas/crear/',
            data=json.dumps({
                'nombre': 'Mercado Pago',
                'tipo': 'billetera',
                'saldo_inicial': 40000,
                'presupuesto_id': self.presupuesto.id,
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_cta.status_code, 201)
        self.assertTrue(resp_cta.json()['success'])
        self.assertEqual(resp_cta.json()['cuenta']['nombre'], 'Mercado Pago')

        # 2. Ingresar efectivo y transferir 30000 de Efectivo a Mercado Pago
        self.client.post(
            '/api/ingresos/crear/',
            data=json.dumps({
                'presupuesto_id': self.presupuesto.id,
                'nombre': 'Efectivo inicial',
                'monto': 50000,
                'tipo_ingreso': 'efectivo',
            }),
            content_type='application/json',
            **self.auth_headers
        )
        resp_trans = self.client.post(
            '/api/transferencias/crear/',
            data=json.dumps({
                'presupuesto_id': self.presupuesto.id,
                'origen_tipo': 'efectivo',
                'destino_tipo': 'cuenta',
                'destino_cuenta': 'Mercado Pago',
                'monto': 30000,
                'nota': 'Depósito en efectivo',
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_trans.status_code, 201)

        # 3. Consultar detalle del presupuesto para las 4 pestañas de la App
        resp_det = self.client.get(
            f'/api/presupuestos/{self.presupuesto.id}/detalle/',
            **self.auth_headers
        )
        self.assertEqual(resp_det.status_code, 200)
        det = resp_det.json()
        self.assertTrue(det['success'])
        self.assertEqual(det['presupuesto']['id'], self.presupuesto.id)
        self.assertEqual(det['cuentas']['saldo_efectivo'], 20000.0)
        mp_item = next((c for c in det['cuentas']['items'] if c['name'] == 'Mercado Pago'), None)
        self.assertIsNotNone(mp_item)
        self.assertEqual(mp_item['balance'], 70000.0)

        # 4. Verificar que la vista /app/ responde 200
        resp_app = self.client.get('/app/')
        self.assertEqual(resp_app.status_code, 200)

    def test_widget_es_rapido_y_editar_eliminar_movimiento(self):
        # 1. Crear gasto desde el widget con es_rapido=True
        resp_create = self.client.post(
            '/api/gastos/crear/',
            data=json.dumps({
                'presupuesto_id': self.presupuesto.id,
                'nombre': 'Kiosco',
                'monto': 2500,
                'metodo_pago': 'efectivo',
                'es_rapido': True,
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_create.status_code, 201)
        gasto_id = resp_create.json()['gasto']['id']
        gasto_obj = Gasto.objects.get(id=gasto_id)
        self.assertTrue(gasto_obj.es_rapido)

        # 2. Editar el gasto desde el modal bottom-sheet y verificar que limpia es_rapido
        resp_edit = self.client.post(
            '/api/movimientos/editar/',
            data=json.dumps({
                'id': gasto_id,
                'tipo_movimiento': 'gasto',
                'nombre': 'Kiosco bebidas',
                'monto': 3200,
                'categoria_id': self.categoria.id,
                'metodo_pago': 'transferencia',
                'cuenta_bancaria': 'Mercado Pago',
                'persona': 'Dario, Camila',
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_edit.status_code, 200)
        gasto_obj.refresh_from_db()
        self.assertFalse(gasto_obj.es_rapido)
        self.assertEqual(gasto_obj.nombre, 'Kiosco bebidas')
        self.assertEqual(gasto_obj.monto, Decimal('3200.00'))
        self.assertEqual(gasto_obj.persona, 'Dario, Camila')

        # 3. Eliminar el gasto desde el modal bottom-sheet
        resp_del = self.client.post(
            '/api/movimientos/eliminar/',
            data=json.dumps({
                'id': gasto_id,
                'tipo_movimiento': 'gasto',
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_del.status_code, 200)
        self.assertFalse(Gasto.objects.filter(id=gasto_id).exists())

    def test_categoria_dinamica_billetera_favorita_orden_y_deteccion_widget(self):
        # 1. Crear 3 billeteras: Ualá (saldo 0), Naranja X (saldo 50000), Mercado Pago (saldo 10000, favorita)
        self.client.post(
            '/api/cuentas/crear/',
            data=json.dumps({
                'nombre': 'Ualá',
                'tipo': 'billetera',
                'saldo_inicial': 0,
                'presupuesto_id': self.presupuesto.id,
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.client.post(
            '/api/cuentas/crear/',
            data=json.dumps({
                'nombre': 'Naranja X',
                'tipo': 'billetera',
                'saldo_inicial': 50000,
                'presupuesto_id': self.presupuesto.id,
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.client.post(
            '/api/cuentas/crear/',
            data=json.dumps({
                'nombre': 'Mercado Pago',
                'tipo': 'billetera',
                'saldo_inicial': 10000,
                'presupuesto_id': self.presupuesto.id,
            }),
            content_type='application/json',
            **self.auth_headers
        )

        # Marcar Mercado Pago como favorita via endpoint /api/cuentas/favorita/
        resp_fav = self.client.post(
            '/api/cuentas/favorita/',
            data=json.dumps({'nombre': 'Mercado Pago'}),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_fav.status_code, 200)
        self.assertTrue(resp_fav.json()['es_favorita'])

        # 2. Verificar el orden en detalle: 1° Favorita (Mercado Pago), 2° Con saldo (Naranja X), luego sin saldo (Ualá)
        resp_det = self.client.get(
            f'/api/presupuestos/{self.presupuesto.id}/detalle/',
            **self.auth_headers
        )
        det = resp_det.json()
        disponibles = [c['nombre'] for c in det['cuentas_disponibles']]
        self.assertEqual(disponibles[0], 'Mercado Pago')
        self.assertEqual(disponibles[1], 'Naranja X')
        self.assertIn('Ualá', disponibles[2:])

        # En cuentas['items'], las billeteras de usuario siguen el mismo orden (Efectivo es fijo pero entre las cuentas de usuario Mercado Pago va primero, luego Naranja X, luego Ualá)
        user_wallet_items = [c['name'] for c in det['cuentas']['items'] if c['name'] in ('Mercado Pago', 'Naranja X', 'Ualá')]
        self.assertEqual(user_wallet_items, ['Mercado Pago', 'Naranja X', 'Ualá'])

        # 3. Crear gasto con nueva categoría escrita ("Mascotas") y transferencia sin especificar cuenta -> usa la favorita (Mercado Pago)
        resp_gasto_cat = self.client.post(
            '/api/gastos/crear/',
            data=json.dumps({
                'presupuesto_id': self.presupuesto.id,
                'nombre': 'Veterinaria',
                'monto': 4000,
                'categoria_nombre': 'Mascotas',
                'metodo_pago': 'transferencia',
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_gasto_cat.status_code, 201)
        g_data = resp_gasto_cat.json()['gasto']
        self.assertEqual(g_data['categoria'], 'Mascotas')
        self.assertEqual(g_data['cuenta_bancaria'], 'Mercado Pago')

        # 4. Widget gasto rápido: detectar 'transferencia' y 'efectivo' desde el concepto
        resp_w_transf = self.client.post(
            '/api/gastos/crear/',
            data=json.dumps({
                'presupuesto_id': self.presupuesto.id,
                'nombre': 'Carniceria transferencia',
                'monto': 8500,
                'metodo_pago': 'efectivo',  # El widget manda 'efectivo' por defecto
                'es_rapido': True,
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_w_transf.status_code, 201)
        gw1 = Gasto.objects.get(id=resp_w_transf.json()['gasto']['id'])
        self.assertEqual(gw1.metodo_pago, 'transferencia')
        self.assertIsNotNone(gw1.cuenta_bancaria)
        self.assertEqual(gw1.cuenta_bancaria.nombre, 'Mercado Pago')

        resp_w_efvo = self.client.post(
            '/api/gastos/crear/',
            data=json.dumps({
                'presupuesto_id': self.presupuesto.id,
                'nombre': 'Verduleria efectivo',
                'monto': 3000,
                'es_rapido': True,
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_w_efvo.status_code, 201)
        gw2 = Gasto.objects.get(id=resp_w_efvo.json()['gasto']['id'])
        self.assertEqual(gw2.metodo_pago, 'efectivo')
        self.assertIsNone(gw2.cuenta_bancaria)



