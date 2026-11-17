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

    def test_tarjeta_fechas_cierre_vencimiento_y_fecha_hora_movimientos(self):
        # 1. Crear tarjeta de crédito con fecha de cierre y fecha de vencimiento
        resp_card = self.client.post(
            '/api/cuentas/crear/',
            data=json.dumps({
                'nombre': 'Visa Patagonia',
                'tipo': 'tarjeta',
                'fecha_cierre': '2026-11-24',
                'fecha_vencimiento': '2026-12-05',
                'presupuesto_id': self.presupuesto.id,
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_card.status_code, 201)
        card_json = resp_card.json()['cuenta']
        self.assertEqual(card_json['fecha_cierre'], '2026-11-24')
        self.assertEqual(card_json['fecha_vencimiento'], '2026-12-05')
        self.assertEqual(card_json['fecha_cierre_str'], '24/11')
        self.assertEqual(card_json['fecha_vencimiento_str'], '05/12')

        # 2. Crear gasto con fecha y hora (datetime-local)
        resp_g = self.client.post(
            '/api/gastos/crear/',
            data=json.dumps({
                'presupuesto_id': self.presupuesto.id,
                'nombre': 'Farmacia',
                'monto': 6500,
                'fecha': '2026-11-16T18:45',
                'metodo_pago': 'tarjeta',
                'cuenta_bancaria': 'Visa Patagonia',
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_g.status_code, 201)
        gid = resp_g.json()['gasto']['id']

        # 3. Editar fecha y hora del gasto desde editar_movimiento_api
        resp_edit = self.client.post(
            '/api/movimientos/editar/',
            data=json.dumps({
                'id': gid,
                'tipo_movimiento': 'gasto',
                'nombre': 'Farmacia turno',
                'monto': 6500,
                'fecha': '2026-11-16T21:30',
                'metodo_pago': 'tarjeta',
                'cuenta_bancaria': 'Visa Patagonia',
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_edit.status_code, 200)

        # 4. Verificar en presupuesto_detalle_api que viene fecha_hora_iso y las fechas de la tarjeta
        resp_det = self.client.get(
            f'/api/presupuestos/{self.presupuesto.id}/detalle/',
            **self.auth_headers
        ).json()
        mov = next((m for m in resp_det['movimientos'] if m['uid'] == f'gasto-{gid}'), None)
        self.assertIsNotNone(mov)
        self.assertEqual(mov['fecha_hora_iso'], '2026-11-16T21:30')
        visa_item = next((c for c in resp_det['cuentas']['items'] if c['name'] == 'Visa Patagonia'), None)
        self.assertIsNotNone(visa_item)
        self.assertEqual(visa_item['fecha_cierre_str'], '24/11')
        self.assertEqual(visa_item['fecha_vencimiento_str'], '05/12')

    def test_presupuesto_abierto_selector_mes_cuotas_y_pago_resumen_tarjeta(self):
        p_abierto = Presupuesto.objects.create(
            usuario=self.user,
            nombre='Flujo Abierto General',
            tipo='abierto',
            monto_total=Decimal('0.00'),
            monto_restante=Decimal('0.00'),
            fecha_inicio=timezone.localdate(),
            fecha_fin=timezone.localdate() + timezone.timedelta(days=365),
            moneda='ARS',
        )

        # 1. Crear billetera favorita con saldo inicial 100.000 y tarjeta Visa
        self.client.post(
            '/api/cuentas/crear/',
            data=json.dumps({
                'nombre': 'Mercado Pago',
                'tipo': 'billetera',
                'saldo_inicial': 100000,
                'es_favorita': True,
                'presupuesto_id': p_abierto.id,
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.client.post(
            '/api/cuentas/crear/',
            data=json.dumps({
                'nombre': 'Visa Patagonia',
                'tipo': 'tarjeta',
                'fecha_cierre': '2026-11-24',
                'fecha_vencimiento': '2026-12-05',
            }),
            content_type='application/json',
            **self.auth_headers
        )

        # 2. Registrar compra con tarjeta en 3 cuotas en Noviembre 2026 (total $60.000 -> $20.000 por cuota)
        resp_cuotas = self.client.post(
            '/api/gastos/crear/',
            data=json.dumps({
                'presupuesto_id': p_abierto.id,
                'nombre': 'Zapatillas',
                'monto': 60000,
                'fecha': '2026-11-17T11:00',
                'metodo_pago': 'tarjeta',
                'cuenta_bancaria': 'Visa Patagonia',
                'cuotas_totales': 3,
                'modo_monto_cuotas': 'total',
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_cuotas.status_code, 201)
        self.assertEqual(resp_cuotas.json()['cuotas_creadas'], 3)
        self.assertEqual(resp_cuotas.json()['gasto']['monto'], 20000.0)
        self.assertEqual(resp_cuotas.json()['gasto']['mes_resumen'], '2026-12')
        self.assertFalse(resp_cuotas.json()['gasto']['es_post_cierre'])

        # 2b. Compra DESPUÉS del cierre de Noviembre (cierra 24/11, compra el 25/11 -> pasa a Enero 2027)
        resp_post = self.client.post(
            '/api/gastos/crear/',
            data=json.dumps({
                'presupuesto_id': p_abierto.id,
                'nombre': 'Campera Post Cierre',
                'monto': 35000,
                'metodo_pago': 'tarjeta',
                'cuenta_bancaria': 'Visa Patagonia',
                'cuotas_totales': 1,
                'fecha': '2026-11-25T19:00',
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_post.status_code, 201)
        self.assertEqual(resp_post.json()['gasto']['mes_resumen'], '2027-01')
        self.assertTrue(resp_post.json()['gasto']['es_post_cierre'])

        # 3. Consultar Noviembre 2026, Diciembre 2026 y Enero 2027 con el selector de mes
        det_nov = self.client.get(
            f'/api/presupuestos/{p_abierto.id}/detalle/?mes=2026-11',
            **self.auth_headers
        ).json()
        self.assertEqual(det_nov['mes_info']['mes_seleccionado'], '2026-11')
        titles_nov = [m['title'] for m in det_nov['movimientos']]
        self.assertIn('Zapatillas (Cuota 1/3)', titles_nov)
        self.assertIn('Campera Post Cierre', titles_nov)
        self.assertEqual(det_nov['mes_info']['total_origen_pasa_siguiente'], 20000.0)
        self.assertEqual(det_nov['mes_info']['total_origen_pasa_subsiguiente'], 35000.0)

        # En Diciembre 2026 el resumen a pagar de la tarjeta incluye Cuota 1/3 (pre-cierre Nov), pero NO la compra post-cierre del 25/11
        det_dic = self.client.get(
            f'/api/presupuestos/{p_abierto.id}/detalle/?mes=2026-12',
            **self.auth_headers
        ).json()
        self.assertEqual(det_dic['mes_info']['mes_seleccionado'], '2026-12')
        titles_dic = [m['title'] for m in det_dic['movimientos']]
        self.assertIn('Zapatillas (Cuota 2/3)', titles_dic)

        visa_dic = next((c for c in det_dic['cuentas']['items'] if c['name'] == 'Visa Patagonia'), None)
        self.assertIsNotNone(visa_dic)
        self.assertEqual(visa_dic['resumen_tarjeta']['total_mes_actual'], 20000.0)
        res_dic_titles = [x['nombre'] for x in visa_dic['resumen_tarjeta']['consumos_mes_actual']]
        self.assertIn('Zapatillas (Cuota 1/3)', res_dic_titles)
        self.assertNotIn('Campera Post Cierre', res_dic_titles)
        self.assertEqual(visa_dic['resumen_tarjeta']['total_mes_siguiente'], 55000.0)  # Cuota 2 ($20k) + Campera post-cierre ($35k) en Enero 2027

        # En Enero 2027 el resumen a pagar de la tarjeta incluye Cuota 2/3 ($20.000) + la compra post-cierre del 25/11 ($35.000)
        det_ene = self.client.get(
            f'/api/presupuestos/{p_abierto.id}/detalle/?mes=2027-01',
            **self.auth_headers
        ).json()
        visa_ene = next((c for c in det_ene['cuentas']['items'] if c['name'] == 'Visa Patagonia'), None)
        self.assertEqual(visa_ene['resumen_tarjeta']['total_mes_actual'], 55000.0)
        res_ene_titles = [x['nombre'] for x in visa_ene['resumen_tarjeta']['consumos_mes_actual']]
        self.assertIn('Zapatillas (Cuota 2/3)', res_ene_titles)
        self.assertIn('Campera Post Cierre', res_ene_titles)
        # En diciembre aún no se habían configurado las fechas de diciembre -> fechas_configuradas_mes es False pero sugiere fecha
        self.assertFalse(visa_dic['fechas_configuradas_mes'])
        self.assertEqual(visa_dic['sugerencia_cierre'], '2026-12-24')

        # Configurar un cierre distinto para Diciembre 2026 (ej. cierra el 22/12 y vence el 06/01)
        self.client.post(
            '/api/cuentas/crear/',
            data=json.dumps({
                'nombre': 'Visa Patagonia',
                'tipo': 'tarjeta',
                'mes': '2026-12',
                'fecha_cierre': '2026-12-22',
                'fecha_vencimiento': '2027-01-06',
            }),
            content_type='application/json',
            **self.auth_headers
        )
        det_dic2 = self.client.get(
            f'/api/presupuestos/{p_abierto.id}/detalle/?mes=2026-12',
            **self.auth_headers
        ).json()
        visa_dic2 = next((c for c in det_dic2['cuentas']['items'] if c['name'] == 'Visa Patagonia'), None)
        self.assertTrue(visa_dic2['fechas_configuradas_mes'])
        self.assertEqual(visa_dic2['fecha_cierre_str'], '22/12')
        self.assertEqual(visa_dic2['fecha_vencimiento_str'], '06/01')

        # Y en Noviembre 2026 sigue conservando su cierre 24/11 y vencimiento 05/12
        det_nov2 = self.client.get(
            f'/api/presupuestos/{p_abierto.id}/detalle/?mes=2026-11',
            **self.auth_headers
        ).json()
        visa_nov2 = next((c for c in det_nov2['cuentas']['items'] if c['name'] == 'Visa Patagonia'), None)
        self.assertEqual(visa_nov2['fecha_cierre_str'], '24/11')
        self.assertEqual(visa_nov2['fecha_vencimiento_str'], '05/12')

        # 4. Pagar en Diciembre 2026 el resumen de Noviembre ($20.000 + $3.500 de impuestos = $23.500)
        resp_pago = self.client.post(
            '/api/tarjetas/pagar-resumen/',
            data=json.dumps({
                'presupuesto_id': p_abierto.id,
                'tarjeta_nombre': 'Visa Patagonia',
                'accion': 'pagar',
                'mes_resumen': '2026-11',
                'monto_diferencia': 3500,
                'concepto_diferencia': 'Impuestos y sellos',
                'monto_total': 23500,
                'metodo_pago': 'transferencia',
                'fecha': '2026-12-05T10:30',
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_pago.status_code, 201)
        p_abierto.refresh_from_db()
        self.assertEqual(p_abierto.monto_restante, Decimal('76500.00'))

        # 5. Compra en cuotas ya iniciada (ej. 6 cuotas, empezando desde la cuota 4/6)
        resp_ini = self.client.post(
            '/api/gastos/crear/',
            data=json.dumps({
                'presupuesto_id': p_abierto.id,
                'nombre': 'Auriculares',
                'monto': 10000,
                'metodo_pago': 'tarjeta',
                'cuenta_bancaria': 'Visa Patagonia',
                'cuotas_totales': 6,
                'cuota_inicial': 4,
                'modo_monto_cuotas': 'cuota',
                'fecha': '2026-11-17T12:00',
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_ini.status_code, 201)
        self.assertEqual(resp_ini.json()['cuotas_creadas'], 3)
        self.assertEqual(resp_ini.json()['gasto']['nombre'], 'Auriculares (Cuota 4/6)')
        self.assertEqual(resp_ini.json()['gasto']['cuota_actual'], 4)
        self.assertEqual(resp_ini.json()['gasto']['mes_resumen'], '2026-12')

        det_nov_ini = self.client.get(
            f'/api/presupuestos/{p_abierto.id}/detalle/?mes=2026-11',
            **self.auth_headers
        ).json()
        titles_nov_ini = [m['title'] for m in det_nov_ini['movimientos']]
        self.assertIn('Auriculares (Cuota 4/6)', titles_nov_ini)
        self.assertNotIn('Auriculares (Cuota 1/6)', titles_nov_ini)

        det_dic_ini = self.client.get(
            f'/api/presupuestos/{p_abierto.id}/detalle/?mes=2026-12',
            **self.auth_headers
        ).json()
        visa_dic_ini = next((c for c in det_dic_ini['cuentas']['items'] if c['name'] == 'Visa Patagonia'), None)
        res_dic_ini_titles = [x['nombre'] for x in visa_dic_ini['resumen_tarjeta']['consumos_mes_actual']]
        self.assertIn('Auriculares (Cuota 4/6)', res_dic_ini_titles)

        # 6. Tarjeta que cierra y vence dentro del MISMO mes (ej. Bna_Visa: cierre 05/11, vencimiento 18/11)
        self.client.post(
            '/api/cuentas/crear/',
            data=json.dumps({
                'nombre': 'Bna_Visa',
                'tipo': 'tarjeta',
                'mes': '2026-11',
                'fecha_cierre': '2026-11-05',
                'fecha_vencimiento': '2026-11-18',
            }),
            content_type='application/json',
            **self.auth_headers
        )
        # Compra el 04/11 (antes del cierre 05/11) -> vence el 18/11 (Noviembre 2026)
        resp_bna_pre = self.client.post(
            '/api/gastos/crear/',
            data=json.dumps({
                'presupuesto_id': p_abierto.id,
                'nombre': 'Gas Pre Cierre BNA',
                'monto': 12000,
                'metodo_pago': 'tarjeta',
                'cuenta_bancaria': 'Bna_Visa',
                'fecha': '2026-11-04T10:00',
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_bna_pre.status_code, 201)
        self.assertEqual(resp_bna_pre.json()['gasto']['mes_resumen'], '2026-11')
        self.assertFalse(resp_bna_pre.json()['gasto']['es_post_cierre'])

        # Compra el 16/11 (después del cierre 05/11) -> cierra el 10/12 y vence en Diciembre 2026
        resp_bna_post = self.client.post(
            '/api/gastos/crear/',
            data=json.dumps({
                'presupuesto_id': p_abierto.id,
                'nombre': 'Gas Post Cierre BNA',
                'monto': 15068,
                'metodo_pago': 'tarjeta',
                'cuenta_bancaria': 'Bna_Visa',
                'fecha': '2026-11-16T21:00',
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_bna_post.status_code, 201)
        self.assertEqual(resp_bna_post.json()['gasto']['mes_resumen'], '2026-12')
        self.assertTrue(resp_bna_post.json()['gasto']['es_post_cierre'])

        # Verificar vence_en_mes en Noviembre 2026 para Bna_Visa y el detalle de consumos + diferencia al pagar en Diciembre 2026
        det_bna_nov = self.client.get(
            f'/api/presupuestos/{p_abierto.id}/detalle/?mes=2026-11',
            **self.auth_headers
        ).json()
        bna_nov = next((c for c in det_bna_nov['cuentas']['items'] if c['name'] == 'Bna_Visa'), None)
        self.assertIsNotNone(bna_nov)
        self.assertTrue(bna_nov['vence_en_mes'])

        resp_bna_pago = self.client.post(
            '/api/tarjetas/pagar-resumen/',
            data=json.dumps({
                'presupuesto_id': p_abierto.id,
                'tarjeta_nombre': 'Bna_Visa',
                'accion': 'pagar',
                'mes_resumen': '2026-12',
                'monto_total': 20000,
                'metodo_pago': 'transferencia',
                'fecha': '2026-12-23T11:00',
            }),
            content_type='application/json',
            **self.auth_headers
        )
        self.assertEqual(resp_bna_pago.status_code, 201)
        self.assertEqual(resp_bna_pago.json()['subtotal_consumos'], 15068.0)
        self.assertEqual(resp_bna_pago.json()['diferencia'], 4932.0)

        det_bna_dic = self.client.get(
            f'/api/presupuestos/{p_abierto.id}/detalle/?mes=2026-12',
            **self.auth_headers
        ).json()
        pago_mov = next((m for m in det_bna_dic['movimientos'] if m['id'] == resp_bna_pago.json()['gasto_id']), None)
        self.assertIsNotNone(pago_mov)
        self.assertIsNotNone(pago_mov['pago_tarjeta_detalle'])
        self.assertEqual(pago_mov['pago_tarjeta_detalle']['subtotal_consumos'], 15068.0)
        self.assertEqual(pago_mov['pago_tarjeta_detalle']['monto_pagado'], 20000.0)
        self.assertEqual(pago_mov['pago_tarjeta_detalle']['diferencia'], 4932.0)
        self.assertEqual(pago_mov['pago_tarjeta_detalle']['consumos'][0]['nombre'], 'Gas Post Cierre BNA')





