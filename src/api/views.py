import json
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date
from django.db.models import Q

from presupuestos.models import (
    Presupuesto,
    Categoria,
    Gasto,
    Ingreso,
    CuentaBancaria,
    TransferenciaFondos,
    CicloPrestamo,
    TarjetaPrestamo,
    DiferenciaTarjeta,
)
from presupuestos.views import (
    presupuestos_editables,
    presupuestos_visibles,
    get_user_recent_personas,
    get_user_recent_cuentas,
)
from .models import ApiToken
from .auth import api_auth_required, get_user_from_request


MESES_ES = [
    '', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'
]
MESES_CORTOS_ES = [
    '', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
    'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'
]
CATEGORY_COLORS = [
    '#6657e8', '#f2766d', '#2baad5', '#e9ad47', '#55d2ad', '#a99fff', '#ec4899', '#38bdf8'
]


def parse_request_data(request):
    """Obtiene los datos tanto si vienen en JSON como en form-data."""
    if request.content_type and 'application/json' in request.content_type:
        try:
            return json.loads(request.body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return {}
    return request.POST.dict()


def format_fecha_humana(dt):
    """Formatea una fecha como 'Hoy, 11:24', 'Ayer, 18:40' o '8 Nov'."""
    if not dt:
        return ''
    if isinstance(dt, datetime):
        if timezone.is_aware(dt):
            local_dt = timezone.localtime(dt)
        else:
            local_dt = dt
        fecha_d = local_dt.date()
        hora_str = local_dt.strftime('%H:%M')
    else:
        fecha_d = dt
        hora_str = ''

    hoy = timezone.localdate()
    ayer = hoy - timezone.timedelta(days=1)
    if fecha_d == hoy:
        return f"Hoy, {hora_str}" if hora_str else "Hoy"
    if fecha_d == ayer:
        return f"Ayer, {hora_str}" if hora_str else "Ayer"
    mes_corto = MESES_CORTOS_ES[fecha_d.month] if 1 <= fecha_d.month <= 12 else ''
    return f"{fecha_d.day} {mes_corto}"


def resolve_gasto_icon_tone(gasto):
    """Determina ícono y color según categoría o medio de pago (estilo Figma)."""
    cat_name = (gasto.categoria.nombre if gasto.categoria else '').lower()
    nombre_low = (gasto.nombre or '').lower()
    combined = f"{cat_name} {nombre_low}"

    if any(k in combined for k in ['super', 'compra', 'ropa', 'tienda', 'mercado', 'coto', 'carrefour', 'regalo']):
        return 'bag', 'rose'
    if any(k in combined for k in ['comida', 'almuerzo', 'cena', 'desayuno', 'restaurante', 'cafe', 'café', 'delivery', 'pedidos', 'alimento']):
        return 'food', 'amber'
    if any(k in combined for k in ['transporte', 'auto', 'nafta', 'ypf', 'shell', 'uber', 'cabify', 'sube', 'peaje', 'viaje', 'colectivo']):
        return 'car', 'blue'
    if any(k in combined for k in ['suscrip', 'netflix', 'spotify', 'servicio', 'luz', 'gas', 'internet', 'alquiler', 'impuesto', 'salud']):
        return 'card', 'violet'
    if gasto.metodo_pago == 'tarjeta':
        return 'card', 'violet'
    return 'bag', 'rose'


def get_user_initials(user):
    first = (user.first_name or '').strip()
    last = (user.last_name or '').strip()
    if first and last:
        return f"{first[0]}{last[0]}".upper()
    if first:
        return first[:2].upper()
    uname = (user.username or 'US').strip()
    return uname[:2].upper()


def get_user_display_name(user):
    if user.first_name:
        return user.first_name.strip().title()
    return (user.username or 'Usuario').strip().title()


@csrf_exempt
@require_http_methods(["POST"])
def login_api(request):
    """
    Autentica al usuario por username o email y devuelve el token de API.
    POST /api/auth/login/
    Body: {"username": "...", "password": "..."}
    """
    data = parse_request_data(request)
    username_or_email = (data.get('username') or data.get('email') or '').strip()
    password = data.get('password', '')

    if not username_or_email or not password:
        return JsonResponse({
            'success': False,
            'error': 'Debes enviar usuario/email y contraseña'
        }, status=400)

    # Si parece un email, buscar el usuario correspondiente
    username = username_or_email
    if '@' in username_or_email:
        user_obj = User.objects.filter(email__iexact=username_or_email).first()
        if user_obj:
            username = user_obj.username

    user = authenticate(request, username=username, password=password)
    if not user or not user.is_active:
        return JsonResponse({
            'success': False,
            'error': 'Credenciales inválidas o cuenta desactivada'
        }, status=401)

    device_name = data.get('device_name', 'Android App / Widget')
    token_obj, _ = ApiToken.objects.get_or_create(
        user=user,
        nombre=device_name
    )

    return JsonResponse({
        'success': True,
        'token': token_obj.token,
        'username': user.username,
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'display_name': get_user_display_name(user),
            'initials': get_user_initials(user),
        }
    })


@require_http_methods(["GET"])
def mi_token_api(request):
    """
    Devuelve o genera el token para el usuario autenticado (útil desde la web o app).
    GET /api/auth/token/
    """
    user = get_user_from_request(request)
    if not user:
        return JsonResponse({'success': False, 'error': 'No autenticado'}, status=401)

    token_obj, _ = ApiToken.objects.get_or_create(
        user=user,
        nombre='Android Widget'
    )
    return JsonResponse({
        'success': True,
        'token': token_obj.token,
        'username': user.username,
        'display_name': get_user_display_name(user),
        'initials': get_user_initials(user),
    })


def serialize_presupuesto_item(p, user, hoy=None):
    if hoy is None:
        hoy = timezone.localdate()
    es_activo = (p.fecha_inicio <= hoy <= p.fecha_fin)
    total_ing = float(p.total_ingresos)
    total_gas_comp = float(p.total_gastos_computables)
    disponible = float(p.monto_total_con_ingresos())
    return {
        'id': p.id,
        'nombre': p.nombre,
        'tipo': p.tipo,
        'tipo_display': p.get_tipo_display(),
        'descripcion': p.descripcion or '',
        'moneda': p.moneda,
        'moneda_display': p.get_moneda_display(),
        'fecha_inicio': p.fecha_inicio.strftime('%Y-%m-%d'),
        'fecha_fin': p.fecha_fin.strftime('%Y-%m-%d'),
        'monto_total': float(p.monto_total),
        'monto_restante': float(p.monto_restante),
        'total_ingresos': total_ing,
        'total_gastos_computables': total_gas_comp,
        'total_tarjeta': float(p.total_tarjeta),
        'saldo_efectivo': float(p.saldo_efectivo),
        'saldo_transferencia': float(p.saldo_transferencia),
        'disponible': disponible,
        'porcentaje_gastado': round(float(p.porcentaje_gastado()), 1),
        'gastos_count': p.gastos.count(),
        'es_activo': es_activo,
        'es_propio': p.usuario_id == user.id,
        'puede_editar': p.puede_editar(user),
    }


@api_auth_required
@require_http_methods(["GET"])
def presupuestos_api(request):
    """
    Lista todos los presupuestos en los que el usuario puede cargar gastos o visualizar.
    GET /api/presupuestos/
    """
    incluir_prestamos = request.GET.get('incluir_prestamos', '0') == '1'
    qs = presupuestos_editables(request.api_user)
    if not incluir_prestamos:
        qs = qs.exclude(tipo='prestamo')
    presupuestos = qs.order_by('-fecha_inicio', '-id')
    hoy = timezone.localdate()

    items = [serialize_presupuesto_item(p, request.api_user, hoy) for p in presupuestos]

    user = request.api_user
    personas_set = set()
    for p in Gasto.objects.filter(presupuesto__usuario=user).exclude(persona='').values_list('persona', flat=True):
        if p:
            for single in p.split(','):
                clean = single.strip().title()
                if clean:
                    personas_set.add(clean)
    personas = sorted(list(personas_set))
    cuentas_qs = CuentaBancaria.objects.filter(usuario=user).order_by('nombre')
    cuentas = list(cuentas_qs.values_list('nombre', flat=True))

    return JsonResponse({
        'success': True,
        'presupuestos': items,
        'personas': personas,
        'cuentas': cuentas,
    })


@api_auth_required
@require_http_methods(["GET"])
def presupuesto_detalle_api(request, pk=None):
    """
    Devuelve todos los datos completos de un presupuesto para las 4 pestañas de la App Android
    (Inicio, Movimientos, Análisis, Cuentas), además del listado de presupuestos para el selector.
    GET /api/presupuestos/<int:pk>/detalle/
    GET /api/presupuestos/activo/detalle/?presupuesto_id=...
    """
    user = request.api_user
    hoy = timezone.localdate()

    todos_qs = presupuestos_visibles(user).order_by('-fecha_inicio', '-id')
    presupuestos_sin_prestamo = todos_qs.exclude(tipo='prestamo')

    target_id = pk or request.GET.get('presupuesto_id')
    presupuesto = None
    if target_id:
        try:
            presupuesto = todos_qs.filter(id=int(target_id)).first()
        except (ValueError, TypeError):
            presupuesto = None

    if not presupuesto:
        presupuesto = presupuestos_sin_prestamo.filter(fecha_inicio__lte=hoy, fecha_fin__gte=hoy).first()
    if not presupuesto:
        presupuesto = presupuestos_sin_prestamo.first() or todos_qs.first()

    # Lista de presupuestos para el selector superior
    presupuestos_selector = [
        serialize_presupuesto_item(p, user, hoy)
        for p in presupuestos_sin_prestamo
    ]
    # Si el usuario tiene préstamos o eligió uno, también los incluimos al final del selector
    prestamos_selector = [
        serialize_presupuesto_item(p, user, hoy)
        for p in todos_qs.filter(tipo='prestamo')
    ]
    all_selector = presupuestos_selector + prestamos_selector

    categorias_disponibles = [
        {'id': c.id, 'nombre': c.nombre}
        for c in Categoria.objects.all().order_by('nombre')
    ]
    personas_disponibles = get_user_recent_personas(user)

    if not presupuesto:
        user_cuentas = list(CuentaBancaria.objects.filter(usuario=user).order_by('nombre'))
        return JsonResponse({
            'success': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'display_name': get_user_display_name(user),
                'initials': get_user_initials(user),
            },
            'presupuesto': None,
            'presupuestos': all_selector,
            'movimientos': [],
            'analisis': {
                'total_gastado': 0,
                'total_computable': 0,
                'total_tarjeta': 0,
                'mayor_categoria': None,
                'categorias': [],
                'personas': [],
            },
            'cuentas': {
                'patrimonio_total': 0,
                'saldo_efectivo': 0,
                'saldo_transferencia': 0,
                'total_tarjeta': 0,
                'items': [
                    {
                        'id': c.id,
                        'name': c.nombre,
                        'subtitle': c.subtitulo_display,
                        'tipo': c.tipo,
                        'balance': 0.0,
                        'icon': 'card' if c.tipo == 'tarjeta' else ('cash' if c.tipo == 'efectivo' else 'wallet'),
                        'icon_class': 'macro' if c.tipo == 'tarjeta' else ('cash' if c.tipo == 'efectivo' else 'mp'),
                        'is_system': False,
                    }
                    for c in user_cuentas
                ],
            },
            'categorias_disponibles': categorias_disponibles,
            'personas_disponibles': personas_disponibles,
            'cuentas_disponibles': [
                {'id': c.id, 'nombre': c.nombre, 'tipo': c.tipo, 'subtitle': c.subtitulo_display}
                for c in user_cuentas
            ],
        })

    # Recopilar movimientos del presupuesto seleccionado
    gastos = list(presupuesto.gastos.select_related('categoria', 'cuenta_bancaria').order_by('-fecha', '-id'))
    ingresos = list(presupuesto.ingresos.select_related('cuenta_bancaria').order_by('-fecha', '-id'))
    transferencias = list(
        presupuesto.transferencias_fondos.select_related('origen_cuenta', 'destino_cuenta').order_by('-fecha', '-id')
    )

    total_gastos_all = sum((g.monto for g in gastos), Decimal('0'))
    total_gastos_comp = sum((g.monto for g in gastos if g.metodo_pago != 'tarjeta'), Decimal('0'))
    total_tarjeta = sum((g.monto for g in gastos if g.metodo_pago == 'tarjeta'), Decimal('0'))
    total_ingresos = sum((i.monto for i in ingresos), Decimal('0'))
    saldo_efectivo = presupuesto.saldo_efectivo
    saldo_transferencia = presupuesto.saldo_transferencia
    disponible = presupuesto.monto_total_con_ingresos()

    # Armar lista unificada de movimientos
    raw_movs = []
    for g in gastos:
        icon, tone = resolve_gasto_icon_tone(g)
        cat_label = g.categoria.nombre if g.categoria else 'Sin categoría'
        parts_detail = [cat_label]
        if g.cuenta_bancaria:
            parts_detail.append(g.cuenta_bancaria.nombre)
        elif g.metodo_pago == 'tarjeta':
            parts_detail.append('Tarjeta')
        elif g.metodo_pago == 'efectivo':
            parts_detail.append('Efectivo')
        if g.persona:
            parts_detail.append(f"👤 {g.persona}")
        parts_detail.append(format_fecha_humana(g.fecha))

        dt_local = timezone.localtime(g.fecha) if timezone.is_aware(g.fecha) else g.fecha
        raw_movs.append({
            '_sort_dt': dt_local,
            'uid': f"gasto-{g.id}",
            'id': g.id,
            'tipo_movimiento': 'gasto',
            'title': g.nombre,
            'detail': ' · '.join([p for p in parts_detail if p]),
            'categoria': cat_label,
            'metodo_pago': g.metodo_pago,
            'cuenta': g.cuenta_bancaria.nombre if g.cuenta_bancaria else ('Efectivo' if g.metodo_pago == 'efectivo' else ''),
            'persona': g.persona or '',
            'amount': -float(g.monto),
            'is_transfer': False,
            'icon': icon,
            'tone': tone,
            'fecha_iso': dt_local.strftime('%Y-%m-%d'),
        })

    for i in ingresos:
        parts_detail = ['Ingreso']
        if i.cuenta_bancaria:
            parts_detail.append(i.cuenta_bancaria.nombre)
        else:
            parts_detail.append(i.get_tipo_ingreso_display())
        parts_detail.append(format_fecha_humana(i.fecha))

        dt_local = timezone.localtime(i.fecha) if timezone.is_aware(i.fecha) else i.fecha
        raw_movs.append({
            '_sort_dt': dt_local,
            'uid': f"ingreso-{i.id}",
            'id': i.id,
            'tipo_movimiento': 'ingreso',
            'title': i.nombre,
            'detail': ' · '.join([p for p in parts_detail if p]),
            'categoria': 'Ingreso',
            'metodo_pago': i.tipo_ingreso,
            'cuenta': i.cuenta_bancaria.nombre if i.cuenta_bancaria else ('Efectivo' if i.tipo_ingreso == 'efectivo' else ''),
            'persona': '',
            'amount': float(i.monto),
            'is_transfer': False,
            'icon': 'cash' if i.tipo_ingreso == 'efectivo' else 'swap',
            'tone': 'green',
            'fecha_iso': dt_local.strftime('%Y-%m-%d'),
        })

    for t in transferencias:
        parts_detail = ['Transferencia', f"{t.origen_str} ➔ {t.destino_str}"]
        if t.nota:
            parts_detail.append(t.nota)
        parts_detail.append(format_fecha_humana(t.fecha))

        dt_local = timezone.localtime(t.fecha) if timezone.is_aware(t.fecha) else t.fecha
        raw_movs.append({
            '_sort_dt': dt_local,
            'uid': f"trans-{t.id}",
            'id': t.id,
            'tipo_movimiento': 'transferencia',
            'title': f"{t.origen_str} ➔ {t.destino_str}",
            'detail': ' · '.join([p for p in parts_detail if p]),
            'categoria': 'Transferencia',
            'metodo_pago': 'transferencia',
            'cuenta': t.destino_str,
            'persona': '',
            'amount': float(t.monto),
            'is_transfer': True,
            'icon': 'swap',
            'tone': 'blue',
            'fecha_iso': dt_local.strftime('%Y-%m-%d'),
        })

    raw_movs.sort(key=lambda x: x['_sort_dt'], reverse=True)
    for m in raw_movs:
        m.pop('_sort_dt', None)

    # Análisis por categoría
    cat_map = {}
    for g in gastos:
        c_name = g.categoria.nombre if g.categoria else 'Sin categoría'
        if c_name not in cat_map:
            cat_map[c_name] = {'name': c_name, 'amount': Decimal('0'), 'count': 0}
        cat_map[c_name]['amount'] += g.monto
        cat_map[c_name]['count'] += 1

    sorted_cats = sorted(cat_map.values(), key=lambda x: (-x['amount'], x['name'].lower()))
    categorias_resumen = []
    for idx, item in enumerate(sorted_cats):
        pct = round(float((item['amount'] / total_gastos_all) * 100)) if total_gastos_all > 0 else 0
        categorias_resumen.append({
            'name': item['name'],
            'amount': float(item['amount']),
            'percent': pct,
            'color': CATEGORY_COLORS[idx % len(CATEGORY_COLORS)],
            'count': item['count'],
        })

    mayor_categoria = categorias_resumen[0] if categorias_resumen else {
        'name': 'Sin gastos',
        'amount': 0.0,
        'percent': 0,
        'color': '#6657e8',
    }

    # Análisis por persona / tag
    pers_map = {}
    for g in gastos:
        if g.persona and g.persona.strip():
            p_parts = [p.strip().title() for p in g.persona.split(',') if p.strip()]
        else:
            p_parts = ['Sin etiqueta']
        for p_nom in p_parts:
            if p_nom not in pers_map:
                pers_map[p_nom] = {'name': p_nom, 'amount': Decimal('0'), 'count': 0}
            pers_map[p_nom]['amount'] += g.monto
            pers_map[p_nom]['count'] += 1

    sorted_pers = sorted(pers_map.values(), key=lambda x: (-x['amount'], x['name'].lower()))
    personas_resumen = []
    for idx, item in enumerate(sorted_pers):
        pct = round(float((item['amount'] / total_gastos_all) * 100)) if total_gastos_all > 0 else 0
        personas_resumen.append({
            'name': item['name'],
            'amount': float(item['amount']),
            'percent': pct,
            'color': CATEGORY_COLORS[idx % len(CATEGORY_COLORS)],
            'count': item['count'],
        })

    # Cuentas y billeteras
    owner = presupuesto.usuario or user
    user_cuentas = list(CuentaBancaria.objects.filter(usuario=owner).order_by('nombre'))
    if user.id != owner.id:
        existing_names = {c.nombre.lower() for c in user_cuentas}
        for c in CuentaBancaria.objects.filter(usuario=user).order_by('nombre'):
            if c.nombre.lower() not in existing_names:
                user_cuentas.append(c)

    # Calcular saldos por CuentaBancaria en este presupuesto
    cuentas_stats = {}
    for c in user_cuentas:
        cuentas_stats[c.nombre.lower()] = {
            'obj': c,
            'nombre': c.nombre,
            'ingresos': Decimal('0'),
            'gastos_liquidos': Decimal('0'),
            'gastos_tarjeta': Decimal('0'),
        }

    for i in ingresos:
        if i.cuenta_bancaria:
            key = i.cuenta_bancaria.nombre.lower()
            if key not in cuentas_stats:
                cuentas_stats[key] = {
                    'obj': i.cuenta_bancaria,
                    'nombre': i.cuenta_bancaria.nombre,
                    'ingresos': Decimal('0'),
                    'gastos_liquidos': Decimal('0'),
                    'gastos_tarjeta': Decimal('0'),
                }
            cuentas_stats[key]['ingresos'] += i.monto

    tarjeta_sin_cuenta = Decimal('0')
    for g in gastos:
        if g.cuenta_bancaria:
            key = g.cuenta_bancaria.nombre.lower()
            if key not in cuentas_stats:
                cuentas_stats[key] = {
                    'obj': g.cuenta_bancaria,
                    'nombre': g.cuenta_bancaria.nombre,
                    'ingresos': Decimal('0'),
                    'gastos_liquidos': Decimal('0'),
                    'gastos_tarjeta': Decimal('0'),
                }
            if g.metodo_pago == 'tarjeta':
                cuentas_stats[key]['gastos_tarjeta'] += g.monto
            else:
                cuentas_stats[key]['gastos_liquidos'] += g.monto
        elif g.metodo_pago == 'tarjeta':
            tarjeta_sin_cuenta += g.monto

    for t in transferencias:
        if t.origen_cuenta:
            key = t.origen_cuenta.nombre.lower()
            if key not in cuentas_stats:
                cuentas_stats[key] = {
                    'obj': t.origen_cuenta,
                    'nombre': t.origen_cuenta.nombre,
                    'ingresos': Decimal('0'),
                    'gastos_liquidos': Decimal('0'),
                    'gastos_tarjeta': Decimal('0'),
                }
            cuentas_stats[key]['gastos_liquidos'] += t.monto
        if t.destino_cuenta:
            key = t.destino_cuenta.nombre.lower()
            if key not in cuentas_stats:
                cuentas_stats[key] = {
                    'obj': t.destino_cuenta,
                    'nombre': t.destino_cuenta.nombre,
                    'ingresos': Decimal('0'),
                    'gastos_liquidos': Decimal('0'),
                    'gastos_tarjeta': Decimal('0'),
                }
            cuentas_stats[key]['ingresos'] += t.monto

    cuentas_items = []
    for key, st in cuentas_stats.items():
        c_obj = st['obj']
        saldo_liq = st['ingresos'] - st['gastos_liquidos']
        gas_tarj = st['gastos_tarjeta']
        sub = c_obj.subtitulo_display if c_obj else 'Billetera virtual'
        c_tipo = c_obj.tipo if c_obj else 'billetera'

        if c_tipo == 'tarjeta' or (sub == 'Tarjeta de crédito' and saldo_liq == 0 and gas_tarj > 0):
            bal = -float(gas_tarj) if gas_tarj > 0 else float(saldo_liq)
            icon_name = 'card'
            icon_cls = 'macro'
        elif c_tipo == 'efectivo':
            bal = float(saldo_liq)
            icon_name = 'cash'
            icon_cls = 'cash'
        else:
            bal = float(saldo_liq)
            icon_name = 'wallet'
            icon_cls = 'mp'

        cuentas_items.append({
            'id': c_obj.id if c_obj else 0,
            'name': st['nombre'],
            'subtitle': sub,
            'tipo': c_tipo,
            'balance': bal,
            'gastos_tarjeta': float(gas_tarj),
            'icon': icon_name,
            'icon_class': icon_cls,
            'is_system': False,
        })

    # Ordenar cuentas: primero las que tienen movimiento o saldo != 0, luego alfabético
    cuentas_items.sort(key=lambda x: (0 if (x['balance'] != 0 or x['gastos_tarjeta'] != 0) else 1, -abs(x['balance']), x['name'].lower()))

    # Agregar Efectivo disponible como cuenta del presupuesto
    cuentas_items.append({
        'id': -1,
        'name': 'Efectivo',
        'subtitle': 'Dinero disponible',
        'tipo': 'efectivo',
        'balance': float(saldo_efectivo),
        'gastos_tarjeta': 0.0,
        'icon': 'cash',
        'icon_class': 'cash',
        'is_system': True,
    })

    # Si hay consumos con tarjeta en este presupuesto, mostrar también el resumen de Tarjeta próximo mes
    if total_tarjeta > 0:
        cuentas_items.append({
            'id': -2,
            'name': 'Tarjetas (Próx. mes)',
            'subtitle': 'Tarjeta de crédito',
            'tipo': 'tarjeta',
            'balance': -float(total_tarjeta),
            'gastos_tarjeta': float(total_tarjeta),
            'icon': 'card',
            'icon_class': 'macro',
            'is_system': True,
        })

    mes_nombre = MESES_ES[presupuesto.fecha_inicio.month].upper() if 1 <= presupuesto.fecha_inicio.month <= 12 else ''
    mes_label = f"{mes_nombre} {presupuesto.fecha_inicio.year}".strip()

    presupuesto_data = serialize_presupuesto_item(presupuesto, user, hoy)
    presupuesto_data['mes_label'] = mes_label
    presupuesto_data['total_gastos_all'] = float(total_gastos_all)

    prestamo_info = None
    if presupuesto.tipo == 'prestamo':
        prestamo_info, raw_movs = build_prestamo_detail_payload(
            presupuesto,
            ciclo_id=request.GET.get('ciclo_id')
        )

    return JsonResponse({
        'success': True,
        'user': {
            'id': user.id,
            'username': user.username,
            'display_name': get_user_display_name(user),
            'initials': get_user_initials(user),
        },
        'presupuesto': presupuesto_data,
        'prestamo_info': prestamo_info,
        'presupuestos': all_selector,
        'movimientos': raw_movs,
        'analisis': {
            'total_gastado': float(total_gastos_all),
            'total_computable': float(total_gastos_comp),
            'total_tarjeta': float(total_tarjeta),
            'mayor_categoria': mayor_categoria,
            'categorias': categorias_resumen,
            'personas': personas_resumen,
        },
        'cuentas': {
            'patrimonio_total': float(presupuesto.monto_restante),
            'saldo_efectivo': float(saldo_efectivo),
            'saldo_transferencia': float(saldo_transferencia),
            'total_tarjeta': float(total_tarjeta),
            'items': cuentas_items,
        },
        'categorias_disponibles': categorias_disponibles,
        'personas_disponibles': personas_disponibles,
        'cuentas_disponibles': [
            {'id': c.id, 'nombre': c.nombre, 'tipo': c.tipo, 'subtitle': c.subtitulo_display}
            for c in user_cuentas
        ],
    })


def build_prestamo_detail_payload(presupuesto, ciclo_id=None):
    """Inicializa y serializa toda la estructura de un presupuesto tipo 'prestamo'."""
    if not presupuesto.tarjetas_prestamo.exists():
        TarjetaPrestamo.objects.bulk_create([
            TarjetaPrestamo(
                presupuesto=presupuesto,
                nombre="Patagonia Rubén",
                dia_cierre_habitual=21,
                proxima_fecha_cierre=date(2026, 11, 19),
                dia_vencimiento_habitual=5,
                nota="Vence del 1 al 5"
            ),
            TarjetaPrestamo(
                presupuesto=presupuesto,
                nombre="Patagonia Palmira",
                dia_cierre_habitual=22,
                proxima_fecha_cierre=date(2026, 11, 19),
                dia_vencimiento_habitual=5,
                nota="Vence del 1 al 5"
            ),
            TarjetaPrestamo(
                presupuesto=presupuesto,
                nombre="Naranja",
                dia_cierre_habitual=27,
                proxima_fecha_cierre=date(2026, 11, 27),
                dia_vencimiento_habitual=10,
                nota="Vence el 10"
            ),
        ])

    if not presupuesto.ciclos_prestamo.exists():
        ciclo_inicial = CicloPrestamo.objects.create(
            presupuesto=presupuesto,
            nombre="Período Noviembre 2026",
            fecha_inicio=date(2026, 10, 21),
            deuda_a_devolver=presupuesto.deuda_inicial_prestamo or Decimal('10129746.00'),
            esta_cerrado=False
        )
        presupuesto.ingresos.filter(ciclo_prestamo__isnull=True).update(ciclo_prestamo=ciclo_inicial)

    ciclos = list(presupuesto.ciclos_prestamo.all())
    ciclo_activo = next((c for c in ciclos if not c.esta_cerrado), None)
    if ciclo_activo:
        presupuesto.ingresos.filter(ciclo_prestamo__isnull=True).update(ciclo_prestamo=ciclo_activo)

    ciclo_sel = None
    if ciclo_id:
        try:
            cid = int(ciclo_id)
            ciclo_sel = next((c for c in ciclos if c.id == cid), None)
        except (ValueError, TypeError):
            ciclo_sel = None
    if not ciclo_sel:
        ciclo_sel = ciclo_activo or (ciclos[0] if ciclos else None)

    tasa_default = float(presupuesto.tasa_interes_prestamo or Decimal('4.50'))
    aporte_habitual = presupuesto.aporte_mensual_prestamo or Decimal('600000.00')
    tasa_factor = Decimal('1') + ((presupuesto.tasa_interes_prestamo or Decimal('4.50')) / Decimal('100'))

    tarjetas_list = []
    for t in presupuesto.tarjetas_prestamo.all():
        info = t.info_cierre()
        ext_qs = ciclo_sel.ingresos.filter(es_extraccion_tarjeta=True, tarjeta_prestamo=t) if ciclo_sel else []
        ext_monto = sum((i.monto for i in ext_qs), Decimal('0'))
        ext_interes = sum((Decimal(str(i.interes_monto)) for i in ext_qs), Decimal('0'))
        ext_prox = sum(((i.monto_proximo_mes or round(i.monto * tasa_factor, 2)) for i in ext_qs), Decimal('0'))
        diffs_qs = list(ciclo_sel.diferencias_tarjetas.filter(tarjeta=t)) if ciclo_sel else []
        diff_total = sum((d.monto for d in diffs_qs), Decimal('0'))

        tarjetas_list.append({
            'id': t.id,
            'nombre': t.nombre,
            'dia_cierre_habitual': t.dia_cierre_habitual,
            'dia_vencimiento_habitual': t.dia_vencimiento_habitual,
            'proxima_fecha_cierre': t.proxima_fecha_cierre.strftime('%Y-%m-%d') if t.proxima_fecha_cierre else '',
            'proxima_fecha_vencimiento': t.proxima_fecha_vencimiento.strftime('%Y-%m-%d') if t.proxima_fecha_vencimiento else '',
            'nota': t.nota or '',
            'ya_cerro': info['ya_cerro'],
            'es_seguro_sacar': info['es_seguro_sacar'],
            'fecha_cierre_str': info['fecha_cierre'].strftime('%d/%m'),
            'fecha_vencimiento_str': info['fecha_vencimiento'].strftime('%d/%m'),
            'dias_para_cierre': info['dias_para_cierre'],
            'mensaje': info['mensaje'],
            'extraido_ciclo': float(ext_monto),
            'interes_ciclo': float(ext_interes),
            'proximo_mes_ciclo': float(ext_prox),
            'diferencias_ciclo': float(diff_total),
        })

    movs_prestamo = []
    diferencias_list = []
    ciclo_actual_data = None

    if ciclo_sel:
        deuda_prox = ciclo_sel.deuda_proximo_ciclo()
        tarj_nec = max(Decimal('0'), deuda_prox - aporte_habitual)
        ciclo_actual_data = {
            'id': ciclo_sel.id,
            'nombre': ciclo_sel.nombre,
            'fecha_inicio': ciclo_sel.fecha_inicio.strftime('%Y-%m-%d'),
            'fecha_fin': ciclo_sel.fecha_fin.strftime('%Y-%m-%d') if ciclo_sel.fecha_fin else '',
            'esta_cerrado': ciclo_sel.esta_cerrado,
            'deuda_base': float(ciclo_sel.deuda_a_devolver),
            'total_diferencias': float(ciclo_sel.total_diferencias()),
            'deuda_total_a_devolver': float(ciclo_sel.deuda_total_a_devolver()),
            'total_extraido_tarjetas': float(ciclo_sel.total_tarjetas()),
            'total_interes_tarjetas': float(ciclo_sel.total_interes_tarjetas()),
            'deuda_proximo_ciclo': float(deuda_prox),
            'total_aportes_efectivo': float(ciclo_sel.total_efectivo()),
            'total_devuelto': float(ciclo_sel.total_devuelto()),
            'pendiente_devolver': float(ciclo_sel.pendiente_devolver()),
            'porcentaje_cubierto': int(ciclo_sel.porcentaje_cubierto()),
            'tarjeta_necesaria_proximo_mes': float(tarj_nec),
        }

        for i in ciclo_sel.ingresos.select_related('cuenta_bancaria', 'tarjeta_prestamo').order_by('-fecha', '-id'):
            dt_local = timezone.localtime(i.fecha) if timezone.is_aware(i.fecha) else i.fecha
            if i.es_extraccion_tarjeta:
                t_nom = i.tarjeta_prestamo.nombre if i.tarjeta_prestamo else i.nombre
                prox = float(i.monto_proximo_mes or round(i.monto * tasa_factor, 2))
                inter = float(i.interes_monto)
                det_parts = [
                    f"💳 {t_nom}",
                    f"+{float(i.tasa_interes or tasa_default):.1f}% (+${inter:,.0f})",
                    f"Vence próx.: ${prox:,.0f}",
                    format_fecha_humana(i.fecha),
                ]
                movs_prestamo.append({
                    '_sort_dt': dt_local,
                    'uid': f"ingreso-{i.id}",
                    'id': i.id,
                    'tipo_movimiento': 'extraccion_tarjeta',
                    'title': i.nombre,
                    'detail': ' · '.join(det_parts),
                    'categoria': 'Extracción Tarjeta',
                    'metodo_pago': 'tarjeta',
                    'cuenta': t_nom,
                    'persona': '',
                    'amount': float(i.monto),
                    'monto_proximo_mes': prox,
                    'interes_monto': inter,
                    'is_transfer': False,
                    'icon': 'card',
                    'tone': 'amber',
                    'fecha_iso': dt_local.strftime('%Y-%m-%d'),
                })
            else:
                det_parts = [
                    '💵 Aporte propio en efectivo',
                    'Sin interés (amortiza deuda)',
                    format_fecha_humana(i.fecha),
                ]
                movs_prestamo.append({
                    '_sort_dt': dt_local,
                    'uid': f"ingreso-{i.id}",
                    'id': i.id,
                    'tipo_movimiento': 'aporte_efectivo',
                    'title': i.nombre,
                    'detail': ' · '.join(det_parts),
                    'categoria': 'Aporte Efectivo',
                    'metodo_pago': 'efectivo',
                    'cuenta': 'Efectivo',
                    'persona': '',
                    'amount': float(i.monto),
                    'is_transfer': False,
                    'icon': 'cash',
                    'tone': 'green',
                    'fecha_iso': dt_local.strftime('%Y-%m-%d'),
                })

        for d in ciclo_sel.diferencias_tarjetas.select_related('tarjeta').all():
            diferencias_list.append({
                'id': d.id,
                'tarjeta_id': d.tarjeta_id,
                'tarjeta_nombre': d.tarjeta.nombre,
                'monto': float(d.monto),
                'concepto': d.concepto,
                'fecha': d.fecha.strftime('%d/%m/%Y'),
            })
            dt_d = timezone.make_aware(datetime.combine(d.fecha, datetime.min.time()), timezone.get_current_timezone())
            movs_prestamo.append({
                '_sort_dt': dt_d,
                'uid': f"diff-{d.id}",
                'id': d.id,
                'tipo_movimiento': 'diferencia_tarjeta',
                'title': f"Dif. Resumen · {d.tarjeta.nombre}",
                'detail': f"{d.concepto} · Suma al monto a devolver actual · {d.fecha.strftime('%d/%m')}",
                'categoria': 'Diferencia Tarjeta',
                'metodo_pago': 'tarjeta',
                'cuenta': d.tarjeta.nombre,
                'persona': '',
                'amount': -float(d.monto),
                'is_transfer': False,
                'icon': 'card',
                'tone': 'rose',
                'fecha_iso': d.fecha.strftime('%Y-%m-%d'),
            })

    movs_prestamo.sort(key=lambda x: x['_sort_dt'], reverse=True)
    for m in movs_prestamo:
        m.pop('_sort_dt', None)

    prestamo_payload = {
        'tasa_interes': tasa_default,
        'aporte_habitual': float(aporte_habitual),
        'ciclo_actual': ciclo_actual_data,
        'ciclos': [
            {
                'id': c.id,
                'nombre': c.nombre,
                'fecha_inicio': c.fecha_inicio.strftime('%d/%m/%Y'),
                'esta_cerrado': c.esta_cerrado,
                'deuda_total_a_devolver': float(c.deuda_total_a_devolver()),
                'total_devuelto': float(c.total_devuelto()),
                'porcentaje_cubierto': int(c.porcentaje_cubierto()),
            }
            for c in ciclos
        ],
        'tarjetas': tarjetas_list,
        'diferencias': diferencias_list,
        'proyeccion': presupuesto.proyeccion_prestamo(),
    }
    return prestamo_payload, movs_prestamo



@csrf_exempt
@api_auth_required
@require_http_methods(["POST"])
def crear_cuenta_api(request):
    """
    Crea o actualiza una CuentaBancaria del usuario desde la pestaña Cuentas de la App.
    Opcionalmente registra un saldo inicial en el presupuesto activo.
    POST /api/cuentas/crear/
    Body:
    {
        "nombre": "Mercado Pago",
        "tipo": "billetera", // billetera | banco | tarjeta
        "saldo_inicial": 50000, // opcional
        "presupuesto_id": 1 // opcional para acreditar saldo_inicial
    }
    """
    data = parse_request_data(request)
    nombre_raw = (data.get('nombre') or '').strip()
    if not nombre_raw:
        return JsonResponse({'success': False, 'error': 'El nombre de la cuenta es obligatorio'}, status=400)

    tipo = (data.get('tipo') or 'billetera').strip().lower()
    if tipo not in ['billetera', 'banco', 'tarjeta', 'efectivo']:
        tipo = 'billetera'

    nombre_clean = nombre_raw[:60]
    cuenta = CuentaBancaria.objects.filter(usuario=request.api_user, nombre__iexact=nombre_clean).first()
    created = False
    if cuenta:
        cuenta.nombre = nombre_clean
        cuenta.tipo = tipo
        cuenta.save()
    else:
        cuenta = CuentaBancaria.objects.create(
            usuario=request.api_user,
            nombre=nombre_clean,
            tipo=tipo,
        )
        created = True

    # Si se indicó un saldo inicial positivo y un presupuesto editable, crear ingreso inicial
    saldo_inicial_raw = data.get('saldo_inicial')
    presupuesto_id = data.get('presupuesto_id')
    if saldo_inicial_raw not in [None, '', '0', 0]:
        try:
            monto_ini = Decimal(str(saldo_inicial_raw).replace(',', '.'))
            if monto_ini > 0 and presupuesto_id:
                presupuesto = presupuestos_editables(request.api_user).filter(id=presupuesto_id).first()
                if presupuesto:
                    Ingreso.objects.create(
                        presupuesto=presupuesto,
                        nombre=f"Saldo inicial · {cuenta.nombre}",
                        monto=monto_ini,
                        tipo_ingreso='transferencia',
                        cuenta_bancaria=cuenta,
                        es_rapido=False,
                    )
        except (InvalidOperation, TypeError):
            pass

    return JsonResponse({
        'success': True,
        'created': created,
        'mensaje': f'Cuenta "{cuenta.nombre}" guardada correctamente',
        'cuenta': {
            'id': cuenta.id,
            'nombre': cuenta.nombre,
            'tipo': cuenta.tipo,
            'subtitle': cuenta.subtitulo_display,
        }
    }, status=201 if created else 200)


@csrf_exempt
@api_auth_required
@require_http_methods(["POST"])
def eliminar_cuenta_api(request, pk):
    """
    Elimina una CuentaBancaria del usuario.
    POST /api/cuentas/<int:pk>/eliminar/
    """
    cuenta = CuentaBancaria.objects.filter(id=pk, usuario=request.api_user).first()
    if not cuenta:
        return JsonResponse({'success': False, 'error': 'Cuenta no encontrada'}, status=404)
    nombre = cuenta.nombre
    cuenta.delete()
    return JsonResponse({
        'success': True,
        'mensaje': f'Cuenta "{nombre}" eliminada'
    })


@csrf_exempt
@api_auth_required
@require_http_methods(["POST"])
def crear_transferencia_api(request):
    """
    Registra una transferencia de fondos entre Efectivo y Cuentas Bancarias / Billeteras.
    POST /api/transferencias/crear/
    Body:
    {
        "presupuesto_id": 1,
        "origen_tipo": "efectivo" | "cuenta",
        "origen_cuenta": "Patagonia", // si origen_tipo == "cuenta"
        "destino_tipo": "cuenta" | "efectivo",
        "destino_cuenta": "Mercadopago", // si destino_tipo == "cuenta"
        "monto": 30000,
        "nota": "Depósito en efectivo"
    }
    """
    data = parse_request_data(request)
    presupuesto_id = data.get('presupuesto_id')
    monto_raw = data.get('monto')

    if not presupuesto_id or monto_raw is None:
        return JsonResponse({'success': False, 'error': 'Faltan datos obligatorios'}, status=400)

    try:
        monto = Decimal(str(monto_raw).replace(',', '.'))
        if monto <= 0:
            return JsonResponse({'success': False, 'error': 'El monto debe ser mayor a cero'}, status=400)
    except (InvalidOperation, TypeError):
        return JsonResponse({'success': False, 'error': 'Monto inválido'}, status=400)

    presupuesto = presupuestos_editables(request.api_user).filter(id=presupuesto_id).first()
    if not presupuesto:
        return JsonResponse({'success': False, 'error': 'Presupuesto no encontrado'}, status=404)

    origen_tipo = (data.get('origen_tipo') or 'efectivo').strip().lower()
    destino_tipo = (data.get('destino_tipo') or 'cuenta').strip().lower()
    if origen_tipo not in ['efectivo', 'cuenta']:
        origen_tipo = 'efectivo'
    if destino_tipo not in ['efectivo', 'cuenta']:
        destino_tipo = 'cuenta'

    if origen_tipo == 'efectivo' and destino_tipo == 'efectivo':
        return JsonResponse({'success': False, 'error': 'Origen y destino no pueden ser ambos Efectivo'}, status=400)

    origen_cuenta = None
    if origen_tipo == 'cuenta':
        orig_raw = (data.get('origen_cuenta') or '').strip()
        if not orig_raw:
            return JsonResponse({'success': False, 'error': 'Selecciona la cuenta de origen'}, status=400)
        origen_cuenta, _ = CuentaBancaria.objects.get_or_create(
            usuario=request.api_user,
            nombre__iexact=orig_raw,
            defaults={'nombre': orig_raw}
        )

    destino_cuenta = None
    if destino_tipo == 'cuenta':
        dest_raw = (data.get('destino_cuenta') or '').strip()
        if not dest_raw:
            return JsonResponse({'success': False, 'error': 'Selecciona la cuenta de destino'}, status=400)
        destino_cuenta, _ = CuentaBancaria.objects.get_or_create(
            usuario=request.api_user,
            nombre__iexact=dest_raw,
            defaults={'nombre': dest_raw}
        )

    if origen_tipo == 'cuenta' and destino_tipo == 'cuenta' and origen_cuenta and destino_cuenta:
        if origen_cuenta.id == destino_cuenta.id:
            return JsonResponse({'success': False, 'error': 'La cuenta de origen y destino no pueden ser la misma'}, status=400)

    nota = (data.get('nota') or '').strip()[:200]
    trans = TransferenciaFondos(
        presupuesto=presupuesto,
        origen_tipo=origen_tipo,
        origen_cuenta=origen_cuenta,
        destino_tipo=destino_tipo,
        destino_cuenta=destino_cuenta,
        monto=monto,
        nota=nota,
    )
    trans.full_clean()
    trans.save()

    return JsonResponse({
        'success': True,
        'mensaje': f'Transferencia de {presupuesto.get_moneda_display()}{monto} registrada',
        'transferencia': {
            'id': trans.id,
            'nombre': trans.nombre,
            'monto': float(trans.monto),
            'origen': trans.origen_str,
            'destino': trans.destino_str,
        }
    }, status=201)


@api_auth_required
@require_http_methods(["GET"])
def metadata_api(request):
    """
    Lista las personas (tags) y cuentas bancarias usadas por el usuario
    ordenadas por los últimos usados para selección rápida tipo tags/chips en la app y widget.
    GET /api/metadata/
    """
    user = request.api_user
    personas = get_user_recent_personas(user)
    cuentas = get_user_recent_cuentas(user)
    return JsonResponse({
        'success': True,
        'personas': personas,
        'cuentas': cuentas
    })


@api_auth_required
@require_http_methods(["GET"])
def categorias_api(request):
    """
    Lista las categorías disponibles para clasificar gastos.
    GET /api/categorias/
    """
    categorias = Categoria.objects.all().order_by('nombre')
    return JsonResponse({
        'success': True,
        'categorias': [
            {
                'id': c.id,
                'nombre': c.nombre,
                'descripcion': c.descripcion or ''
            }
            for c in categorias
        ]
    })


@csrf_exempt
@api_auth_required
@require_http_methods(["POST"])
def crear_gasto_api(request):
    """
    Registra un nuevo gasto desde la app o widget.
    POST /api/gastos/crear/
    """
    data = parse_request_data(request)
    presupuesto_id = data.get('presupuesto_id')
    nombre = (data.get('nombre') or '').strip()
    monto_raw = data.get('monto')

    if not presupuesto_id:
        return JsonResponse({'success': False, 'error': 'Falta el presupuesto_id'}, status=400)
    if monto_raw is None:
        return JsonResponse({'success': False, 'error': 'El monto es obligatorio'}, status=400)

    try:
        monto = Decimal(str(monto_raw).replace(',', '.'))
        if monto <= 0:
            return JsonResponse({'success': False, 'error': 'El monto debe ser mayor a cero'}, status=400)
    except (InvalidOperation, TypeError):
        return JsonResponse({'success': False, 'error': 'El monto no es un número válido'}, status=400)

    # Validar permisos de edición en el presupuesto
    presupuesto = presupuestos_editables(request.api_user).filter(id=presupuesto_id).first()
    if not presupuesto:
        return JsonResponse({
            'success': False,
            'error': 'Presupuesto no encontrado o no tienes permiso para cargar gastos en él'
        }, status=404)

    es_rapido = False
    # Si no se especificó nombre, asignar nombre automático secuencial
    if not nombre:
        es_rapido = True
        count_rapidos = Gasto.objects.filter(
            presupuesto=presupuesto
        ).filter(
            Q(nombre__icontains='rápido') | Q(nombre__icontains='rapido') | Q(nombre__startswith='⚡')
        ).count()
        nombre = f"⚡ Gasto rápido {count_rapidos + 1:02d}"

    # Categoría opcional (por ID o por nombre)
    categoria = None
    categoria_id = data.get('categoria_id')
    categoria_nombre = (data.get('categoria_nombre') or '').strip()
    if categoria_id:
        categoria = Categoria.objects.filter(id=categoria_id).first()
    elif categoria_nombre:
        categoria = Categoria.objects.filter(nombre__iexact=categoria_nombre).first()

    # Fecha opcional
    fecha = None
    fecha_raw = (data.get('fecha') or '').strip()
    if fecha_raw:
        parsed_dt = parse_datetime(fecha_raw)
        if parsed_dt:
            fecha = parsed_dt
        else:
            parsed_d = parse_date(fecha_raw)
            if parsed_d:
                now_local = timezone.localtime(timezone.now())
                fecha = timezone.make_aware(
                    datetime.combine(parsed_d, now_local.time()),
                    timezone.get_current_timezone()
                )

    descripcion = (data.get('descripcion') or '').strip()
    metodo_pago = (data.get('metodo_pago') or 'efectivo').lower().strip()
    if metodo_pago not in ['efectivo', 'transferencia', 'tarjeta']:
        metodo_pago = 'efectivo'

    persona_raw = (data.get('persona') or '').strip()
    if persona_raw:
        parts = [p.strip().title() for p in persona_raw.split(',') if p.strip()]
        seen = []
        for p in parts:
            if p not in seen:
                seen.append(p)
        persona = ', '.join(seen)
    else:
        persona = ''

    cuenta_bancaria = None
    cuenta_raw = (data.get('cuenta_bancaria') or '').strip()
    if cuenta_raw and metodo_pago != 'efectivo' and cuenta_raw.lower() != 'efectivo':
        cuenta_bancaria = CuentaBancaria.objects.filter(
            usuario=request.api_user,
            nombre__iexact=cuenta_raw
        ).first()
        if not cuenta_bancaria:
            cuenta_bancaria = CuentaBancaria.objects.create(
                usuario=request.api_user,
                nombre=cuenta_raw.title(),
                tipo='tarjeta' if metodo_pago == 'tarjeta' else 'billetera'
            )

    gasto = Gasto(
        presupuesto=presupuesto,
        categoria=categoria,
        nombre=nombre,
        persona=persona,
        cuenta_bancaria=cuenta_bancaria,
        monto=monto,
        metodo_pago=metodo_pago,
        descripcion=descripcion or None,
        fecha=fecha or timezone.localtime(timezone.now()),
        es_rapido=es_rapido
    )
    gasto.full_clean()
    gasto.save()

    presupuesto.refresh_from_db()

    return JsonResponse({
        'success': True,
        'mensaje': f'Gasto de {presupuesto.moneda} {monto} registrado exitosamente',
        'gasto': {
            'id': gasto.id,
            'nombre': gasto.nombre,
            'persona': gasto.persona,
            'cuenta_bancaria': gasto.cuenta_bancaria.nombre if gasto.cuenta_bancaria else None,
            'metodo_pago': gasto.metodo_pago,
            'monto': float(gasto.monto),
            'categoria': gasto.categoria.nombre if gasto.categoria else None,
            'fecha': gasto.fecha.strftime('%Y-%m-%d %H:%M'),
        },
        'presupuesto': {
            'id': presupuesto.id,
            'nombre': presupuesto.nombre,
            'moneda': presupuesto.moneda,
            'monto_restante': float(presupuesto.monto_restante),
            'porcentaje_gastado': round(float(presupuesto.porcentaje_gastado()), 1),
        }
    }, status=201)


@csrf_exempt
@api_auth_required
@require_http_methods(["POST"])
def crear_ingreso_api(request):
    """
    Registra un nuevo ingreso.
    POST /api/ingresos/crear/
    """
    data = parse_request_data(request)
    presupuesto_id = data.get('presupuesto_id')
    nombre = (data.get('nombre') or '').strip()
    monto_raw = data.get('monto')

    if not presupuesto_id or monto_raw is None:
        return JsonResponse({'success': False, 'error': 'Faltan campos obligatorios'}, status=400)

    try:
        monto = Decimal(str(monto_raw).replace(',', '.'))
        if monto <= 0:
            return JsonResponse({'success': False, 'error': 'El monto debe ser positivo'}, status=400)
    except (InvalidOperation, TypeError):
        return JsonResponse({'success': False, 'error': 'Monto inválido'}, status=400)

    presupuesto = presupuestos_editables(request.api_user).filter(id=presupuesto_id).first()
    if not presupuesto:
        return JsonResponse({'success': False, 'error': 'Presupuesto no encontrado'}, status=404)

    es_rapido = False
    # Si no se especificó nombre, asignar nombre automático secuencial
    if not nombre:
        es_rapido = True
        count_rapidos = Ingreso.objects.filter(
            presupuesto=presupuesto
        ).filter(
            Q(nombre__icontains='rápido') | Q(nombre__icontains='rapido') | Q(nombre__startswith='⚡')
        ).count()
        nombre = f"⚡ Ingreso rápido {count_rapidos + 1:02d}"

    tipo_ingreso = (data.get('tipo_ingreso') or 'transferencia').lower().strip()
    if tipo_ingreso not in ['transferencia', 'efectivo', 'sueldo']:
        tipo_ingreso = 'transferencia'

    cuenta_bancaria = None
    cuenta_raw = (data.get('cuenta_bancaria') or '').strip()
    if cuenta_raw and tipo_ingreso != 'efectivo' and cuenta_raw.lower() != 'efectivo':
        cuenta_bancaria = CuentaBancaria.objects.filter(
            usuario=request.api_user,
            nombre__iexact=cuenta_raw
        ).first()
        if not cuenta_bancaria:
            cuenta_bancaria = CuentaBancaria.objects.create(
                usuario=request.api_user,
                nombre=cuenta_raw.title(),
                tipo='billetera'
            )

    fecha = None
    fecha_raw = (data.get('fecha') or '').strip()
    if fecha_raw:
        parsed_dt = parse_datetime(fecha_raw)
        if parsed_dt:
            fecha = parsed_dt
        else:
            parsed_d = parse_date(fecha_raw)
            if parsed_d:
                now_local = timezone.localtime(timezone.now())
                fecha = timezone.make_aware(
                    datetime.combine(parsed_d, now_local.time()),
                    timezone.get_current_timezone()
                )

    ingreso = Ingreso(
        presupuesto=presupuesto,
        nombre=nombre,
        monto=monto,
        tipo_ingreso=tipo_ingreso,
        cuenta_bancaria=cuenta_bancaria,
        descripcion=data.get('descripcion') or None,
        fecha=fecha or timezone.localtime(timezone.now()),
        es_rapido=es_rapido
    )
    ingreso.full_clean()
    ingreso.save()

    presupuesto.refresh_from_db()

    return JsonResponse({
        'success': True,
        'mensaje': f'Ingreso de {presupuesto.moneda} {monto} registrado exitosamente',
        'ingreso': {
            'id': ingreso.id,
            'nombre': ingreso.nombre,
            'monto': float(ingreso.monto),
            'tipo_ingreso': ingreso.tipo_ingreso,
            'cuenta_bancaria': ingreso.cuenta_bancaria.nombre if ingreso.cuenta_bancaria else None,
        },
        'presupuesto': {
            'id': presupuesto.id,
            'nombre': presupuesto.nombre,
            'monto_restante': float(presupuesto.monto_restante),
            'disponible': float(presupuesto.monto_total + presupuesto.total_ingresos),
        }
    }, status=201)


@api_auth_required
@require_http_methods(["GET"])
def widget_resumen_api(request):
    """
    Devuelve los datos esenciales para renderizar el Widget en la pantalla de inicio:
    - Saldo y porcentaje del presupuesto actual.
    - Últimos 5 movimientos.
    GET /api/widget/resumen/?presupuesto_id=1
    """
    presupuestos_qs = presupuestos_editables(request.api_user).exclude(tipo='prestamo').order_by('-fecha_inicio')
    presupuesto_id = request.GET.get('presupuesto_id')

    presupuesto = None
    if presupuesto_id:
        presupuesto = presupuestos_qs.filter(id=presupuesto_id).first()

    # Si no se especifica presupuesto, buscar el activo de hoy o el más reciente
    if not presupuesto:
        hoy = timezone.localdate()
        presupuesto = presupuestos_qs.filter(fecha_inicio__lte=hoy, fecha_fin__gte=hoy).first()
        if not presupuesto:
            presupuesto = presupuestos_qs.first()

    if not presupuesto:
        return JsonResponse({
            'success': True,
            'presupuesto': None,
            'mensaje': 'No tienes presupuestos registrados'
        })

    ultimos_gastos = presupuesto.gastos.select_related('categoria').order_by('-fecha')[:5]

    return JsonResponse({
        'success': True,
        'presupuesto': {
            'id': presupuesto.id,
            'nombre': presupuesto.nombre,
            'tipo': presupuesto.tipo,
            'moneda': presupuesto.moneda,
            'moneda_display': presupuesto.get_moneda_display(),
            'monto_restante': float(presupuesto.monto_restante),
            'disponible': float(presupuesto.monto_total_con_ingresos()),
            'saldo_efectivo': float(presupuesto.saldo_efectivo),
            'saldo_transferencia': float(presupuesto.saldo_transferencia),
            'total_tarjeta': float(presupuesto.total_tarjeta),
            'porcentaje_gastado': round(float(presupuesto.porcentaje_gastado()), 1),
            'gastos_count': presupuesto.gastos.count(),
        },
        'ultimos_gastos': [
            {
                'id': g.id,
                'nombre': g.nombre,
                'monto': float(g.monto),
                'categoria': g.categoria.nombre if g.categoria else None,
                'fecha': g.fecha.strftime('%d/%m %H:%M'),
            }
            for g in ultimos_gastos
        ]
    })


@csrf_exempt
@api_auth_required
@require_http_methods(["POST"])
def crear_ingreso_prestamo_api(request):
    """
    Registra un Ingreso con Tarjeta (extracción al 4.5%) o Aporte en Efectivo para un presupuesto tipo 'prestamo'.
    POST /api/prestamo/ingreso/crear/
    """
    data = parse_request_data(request)
    presupuesto_id = data.get('presupuesto_id')
    monto_raw = data.get('monto')
    modo = (data.get('modo') or 'tarjeta').strip().lower()  # 'tarjeta' | 'efectivo'

    if not presupuesto_id or monto_raw is None:
        return JsonResponse({'success': False, 'error': 'Faltan datos obligatorios'}, status=400)

    try:
        monto = Decimal(str(monto_raw).replace(',', '.'))
        if monto <= 0:
            return JsonResponse({'success': False, 'error': 'El monto debe ser mayor a cero'}, status=400)
    except (InvalidOperation, TypeError):
        return JsonResponse({'success': False, 'error': 'Monto inválido'}, status=400)

    presupuesto = presupuestos_editables(request.api_user).filter(id=presupuesto_id, tipo='prestamo').first()
    if not presupuesto:
        return JsonResponse({'success': False, 'error': 'Presupuesto de préstamo no encontrado'}, status=404)

    ciclo_id = data.get('ciclo_id')
    ciclo = None
    if ciclo_id:
        ciclo = presupuesto.ciclos_prestamo.filter(id=ciclo_id).first()
    if not ciclo:
        ciclo = presupuesto.ciclos_prestamo.filter(esta_cerrado=False).first()

    if modo == 'efectivo':
        nombre = (data.get('nombre') or 'Aporte propio en efectivo').strip()
        ingreso = Ingreso.objects.create(
            presupuesto=presupuesto,
            ciclo_prestamo=ciclo,
            nombre=nombre,
            monto=monto,
            tipo_ingreso='efectivo',
            es_aporte_capital=True,
            es_extraccion_tarjeta=False,
        )
        return JsonResponse({
            'success': True,
            'mensaje': f'Aporte en efectivo de ${monto:,.0f} registrado',
            'ingreso_id': ingreso.id,
        }, status=201)

    # Modo tarjeta (extracción con interés)
    tarjeta_id = data.get('tarjeta_id')
    tarjeta = None
    if tarjeta_id:
        tarjeta = presupuesto.tarjetas_prestamo.filter(id=tarjeta_id).first()

    tasa_raw = data.get('tasa_interes')
    try:
        tasa = Decimal(str(tasa_raw).replace(',', '.')) if tasa_raw not in [None, ''] else (presupuesto.tasa_interes_prestamo or Decimal('4.50'))
    except (InvalidOperation, TypeError):
        tasa = presupuesto.tasa_interes_prestamo or Decimal('4.50')

    prox_raw = data.get('monto_proximo_mes')
    try:
        monto_prox = Decimal(str(prox_raw).replace(',', '.')) if prox_raw not in [None, ''] else round(monto * (Decimal('1') + tasa / Decimal('100')), 2)
    except (InvalidOperation, TypeError):
        monto_prox = round(monto * (Decimal('1') + tasa / Decimal('100')), 2)

    nombre_default = f"Extracción {tarjeta.nombre}" if tarjeta else "Extracción con tarjeta"
    nombre = (data.get('nombre') or nombre_default).strip()

    cuenta_bancaria = None
    cuenta_raw = (data.get('cuenta_bancaria') or '').strip()
    if cuenta_raw:
        cuenta_bancaria, _ = CuentaBancaria.objects.get_or_create(
            usuario=request.api_user,
            nombre__iexact=cuenta_raw,
            defaults={'nombre': cuenta_raw.title(), 'tipo': 'billetera'}
        )

    ingreso = Ingreso.objects.create(
        presupuesto=presupuesto,
        ciclo_prestamo=ciclo,
        tarjeta_prestamo=tarjeta,
        cuenta_bancaria=cuenta_bancaria,
        nombre=nombre,
        monto=monto,
        tipo_ingreso='transferencia',
        tasa_interes=tasa,
        monto_proximo_mes=monto_prox,
        es_extraccion_tarjeta=True,
        es_aporte_capital=False,
    )

    return JsonResponse({
        'success': True,
        'mensaje': f'Extracción de ${monto:,.0f} registrada (vence próx. mes: ${monto_prox:,.0f})',
        'ingreso_id': ingreso.id,
    }, status=201)


@csrf_exempt
@api_auth_required
@require_http_methods(["POST"])
def crear_diferencia_prestamo_api(request):
    """
    Agrega una DiferenciaTarjeta (gastos de mantenimiento / sellos de resumen) al ciclo del préstamo.
    POST /api/prestamo/diferencia/crear/
    """
    data = parse_request_data(request)
    presupuesto_id = data.get('presupuesto_id')
    tarjeta_id = data.get('tarjeta_id')
    monto_raw = data.get('monto')

    if not presupuesto_id or not tarjeta_id or monto_raw is None:
        return JsonResponse({'success': False, 'error': 'Faltan datos obligatorios'}, status=400)

    try:
        monto = Decimal(str(monto_raw).replace(',', '.'))
        if monto <= 0:
            return JsonResponse({'success': False, 'error': 'El monto debe ser mayor a cero'}, status=400)
    except (InvalidOperation, TypeError):
        return JsonResponse({'success': False, 'error': 'Monto inválido'}, status=400)

    presupuesto = presupuestos_editables(request.api_user).filter(id=presupuesto_id, tipo='prestamo').first()
    if not presupuesto:
        return JsonResponse({'success': False, 'error': 'Presupuesto no encontrado'}, status=404)

    tarjeta = presupuesto.tarjetas_prestamo.filter(id=tarjeta_id).first()
    if not tarjeta:
        return JsonResponse({'success': False, 'error': 'Tarjeta no encontrada'}, status=404)

    ciclo_id = data.get('ciclo_id')
    ciclo = presupuesto.ciclos_prestamo.filter(id=ciclo_id).first() if ciclo_id else None
    if not ciclo:
        ciclo = presupuesto.ciclos_prestamo.filter(esta_cerrado=False).first()
    if not ciclo:
        return JsonResponse({'success': False, 'error': 'No hay un período activo'}, status=400)

    concepto = (data.get('concepto') or 'Mantenimiento / Sellos resumen').strip()[:150]
    diff = DiferenciaTarjeta.objects.create(
        ciclo_prestamo=ciclo,
        tarjeta=tarjeta,
        monto=monto,
        concepto=concepto,
    )

    return JsonResponse({
        'success': True,
        'mensaje': f'Diferencia de +${monto:,.0f} sumada a {tarjeta.nombre}',
        'diferencia_id': diff.id,
    }, status=201)


@csrf_exempt
@api_auth_required
@require_http_methods(["POST"])
def guardar_tarjeta_prestamo_api(request):
    """
    Crea o actualiza una TarjetaPrestamo (nombre y fechas de cierre/vencimiento).
    POST /api/prestamo/tarjeta/guardar/
    """
    data = parse_request_data(request)
    presupuesto_id = data.get('presupuesto_id')
    nombre = (data.get('nombre') or '').strip()

    if not presupuesto_id or not nombre:
        return JsonResponse({'success': False, 'error': 'El nombre de la tarjeta es obligatorio'}, status=400)

    presupuesto = presupuestos_editables(request.api_user).filter(id=presupuesto_id, tipo='prestamo').first()
    if not presupuesto:
        return JsonResponse({'success': False, 'error': 'Presupuesto no encontrado'}, status=404)

    tarjeta_id = data.get('tarjeta_id')
    tarjeta = presupuesto.tarjetas_prestamo.filter(id=tarjeta_id).first() if tarjeta_id else None

    dia_cierre = int(data.get('dia_cierre_habitual') or 21)
    dia_vence = int(data.get('dia_vencimiento_habitual') or 5)
    prox_cierre = parse_date(str(data.get('proxima_fecha_cierre') or ''))
    prox_vence = parse_date(str(data.get('proxima_fecha_vencimiento') or ''))
    nota = (data.get('nota') or '').strip()[:200]

    if tarjeta:
        tarjeta.nombre = nombre[:100]
        tarjeta.dia_cierre_habitual = dia_cierre
        tarjeta.dia_vencimiento_habitual = dia_vence
        tarjeta.proxima_fecha_cierre = prox_cierre
        tarjeta.proxima_fecha_vencimiento = prox_vence
        tarjeta.nota = nota
        tarjeta.save()
    else:
        tarjeta = TarjetaPrestamo.objects.create(
            presupuesto=presupuesto,
            nombre=nombre[:100],
            dia_cierre_habitual=dia_cierre,
            dia_vencimiento_habitual=dia_vence,
            proxima_fecha_cierre=prox_cierre,
            proxima_fecha_vencimiento=prox_vence,
            nota=nota,
        )

    return JsonResponse({
        'success': True,
        'mensaje': f'Tarjeta "{tarjeta.nombre}" guardada',
        'tarjeta_id': tarjeta.id,
    }, status=201)


@csrf_exempt
@api_auth_required
@require_http_methods(["POST"])
def cerrar_ciclo_prestamo_api(request):
    """
    Cierra el ciclo activo del préstamo e inicia el nuevo período con la deuda del próximo mes.
    POST /api/prestamo/cerrar-ciclo/
    """
    data = parse_request_data(request)
    presupuesto_id = data.get('presupuesto_id')
    nuevo_nombre = (data.get('nuevo_nombre') or '').strip()
    deuda_raw = data.get('deuda_a_devolver')

    if not presupuesto_id or not nuevo_nombre:
        return JsonResponse({'success': False, 'error': 'Indica el nombre del nuevo período'}, status=400)

    presupuesto = presupuestos_editables(request.api_user).filter(id=presupuesto_id, tipo='prestamo').first()
    if not presupuesto:
        return JsonResponse({'success': False, 'error': 'Presupuesto no encontrado'}, status=404)

    ciclo_activo = presupuesto.ciclos_prestamo.filter(esta_cerrado=False).first()
    try:
        deuda_sig = Decimal(str(deuda_raw).replace(',', '.')) if deuda_raw not in [None, ''] else (ciclo_activo.deuda_proximo_ciclo() if ciclo_activo else Decimal('0'))
    except (InvalidOperation, TypeError):
        deuda_sig = ciclo_activo.deuda_proximo_ciclo() if ciclo_activo else Decimal('0')

    nueva_fecha = parse_date(str(data.get('nueva_fecha_inicio') or '')) or timezone.localdate()

    if ciclo_activo:
        ciclo_activo.esta_cerrado = True
        ciclo_activo.fecha_fin = nueva_fecha - timedelta(days=1)
        ciclo_activo.fecha_cierre = timezone.now()
        ciclo_activo.save()

    nuevo_ciclo = CicloPrestamo.objects.create(
        presupuesto=presupuesto,
        nombre=nuevo_nombre[:100],
        fecha_inicio=nueva_fecha,
        deuda_a_devolver=deuda_sig,
        esta_cerrado=False,
    )

    return JsonResponse({
        'success': True,
        'mensaje': f'Período "{nuevo_ciclo.nombre}" iniciado',
        'ciclo_id': nuevo_ciclo.id,
    }, status=201)

