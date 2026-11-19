import calendar
import json
import re
import uuid
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


def normalize_text_plain(text):
    """Normaliza texto en minúsculas y sin tildes para detección de palabras clave."""
    s = (text or '').lower().strip()
    for a, b in [('á', 'a'), ('é', 'e'), ('í', 'i'), ('ó', 'o'), ('ú', 'u')]:
        s = s.replace(a, b)
    return s


def detectar_metodo_y_cuenta_desde_concepto(texto, user):
    """
    Detecta si en el concepto de un movimiento rápido figura 'efectivo' o 'transferencia'
    (o el nombre de una billetera/banco del usuario) y devuelve (metodo_detectado, cuenta_obj).
    """
    norm = normalize_text_plain(texto)
    if not norm:
        return None, None

    words = set(norm.replace(',', ' ').replace('.', ' ').replace('-', ' ').split())
    metodo_detectado = None

    transf_keywords = {'transferencia', 'tranferencia', 'trnsferencia', 'transf', 'mercadopago', 'mp', 'brubank', 'uala'}
    efectivo_keywords = {'efectivo', 'efvo', 'cash'}
    tarjeta_keywords = {'tarjeta', 'credito'}

    if words & efectivo_keywords or 'efectivo' in norm:
        metodo_detectado = 'efectivo'
    elif (
        words & transf_keywords
        or 'transferencia' in norm
        or 'tranferencia' in norm
        or 'trnsferencia' in norm
        or 'mercado pago' in norm
    ):
        metodo_detectado = 'transferencia'
    elif words & tarjeta_keywords or 'tarjeta' in norm:
        metodo_detectado = 'tarjeta'

    cuenta_detectada = None
    if user and metodo_detectado != 'efectivo':
        user_cuentas = list(CuentaBancaria.objects.filter(usuario=user).order_by('-es_favorita', 'nombre'))
        for c in user_cuentas:
            c_norm = normalize_text_plain(c.nombre)
            if c_norm and c_norm in norm:
                cuenta_detectada = c
                if not metodo_detectado:
                    metodo_detectado = 'tarjeta' if c.tipo == 'tarjeta' else 'transferencia'
                break

        if not cuenta_detectada and metodo_detectado == 'transferencia':
            # Si es transferencia y no nombró una billetera específica, usar la favorita si existe
            fav = next((c for c in user_cuentas if c.es_favorita and c.tipo != 'tarjeta'), None)
            if fav:
                cuenta_detectada = fav

    return metodo_detectado, cuenta_detectada


def resolve_or_create_categoria(categoria_id, categoria_nombre):
    """Busca una categoría por nombre (creándola si es nueva) o por ID."""
    cat_nom = (categoria_nombre or '').strip()
    if cat_nom:
        cat = Categoria.objects.filter(nombre__iexact=cat_nom).first()
        if not cat:
            clean_name = cat_nom[:100]
            if clean_name == clean_name.lower():
                clean_name = clean_name.capitalize()
            cat = Categoria.objects.create(nombre=clean_name)
        return cat
    if categoria_id:
        try:
            return Categoria.objects.filter(id=int(categoria_id)).first()
        except (ValueError, TypeError):
            return None
    return None


def parse_fecha_hora_input(fecha_raw):
    """Convierte un string YYYY-MM-DDTHH:MM o YYYY-MM-DD en datetime aware local."""
    s = (fecha_raw or '').strip()
    if not s:
        return None
    parsed_dt = parse_datetime(s)
    if parsed_dt:
        if timezone.is_naive(parsed_dt):
            return timezone.make_aware(parsed_dt, timezone.get_current_timezone())
        return timezone.localtime(parsed_dt)
    parsed_d = parse_date(s)
    if parsed_d:
        now_local = timezone.localtime(timezone.now())
        return timezone.make_aware(
            datetime.combine(parsed_d, now_local.time()),
            timezone.get_current_timezone()
        )
    return None


def resolve_cuenta_tipo(c_obj, saldo_liq=Decimal('0'), gas_tarj=Decimal('0')):
    """Determina y corrige automáticamente el tipo 'tarjeta' para cuentas de tarjeta de crédito."""
    if not c_obj:
        return 'billetera'
    sub = c_obj.subtitulo_display
    if c_obj.tipo == 'tarjeta' or sub == 'Tarjeta de crédito' or (saldo_liq == 0 and gas_tarj > 0):
        if c_obj.tipo != 'tarjeta':
            c_obj.tipo = 'tarjeta'
            c_obj.es_favorita = False
            c_obj.save(update_fields=['tipo', 'es_favorita'])
        return 'tarjeta'
    return c_obj.tipo or 'billetera'


def serialize_cuenta_fechas(c_obj, mes_ym=None):
    """Devuelve fechas de cierre y vencimiento formateadas para tarjetas (por mes seleccionado si aplica)."""
    if not c_obj:
        return {
            'fecha_cierre': '',
            'fecha_vencimiento': '',
            'fecha_cierre_str': '',
            'fecha_vencimiento_str': '',
            'fechas_configuradas_mes': False,
            'sugerencia_cierre': '',
            'sugerencia_vencimiento': '',
        }

    fechas_map = getattr(c_obj, 'fechas_por_mes', None) or {}
    base_fc = getattr(c_obj, 'fecha_cierre', None)
    base_fv = getattr(c_obj, 'fecha_vencimiento', None)

    fc = None
    fv = None
    configurado_mes = False

    if mes_ym and re.match(r'^\d{4}-\d{2}$', str(mes_ym)):
        if mes_ym in fechas_map and isinstance(fechas_map[mes_ym], dict):
            fc_s = (fechas_map[mes_ym].get('fecha_cierre') or '').strip()
            fv_s = (fechas_map[mes_ym].get('fecha_vencimiento') or '').strip()
            fc = parse_date(fc_s) if fc_s else None
            fv = parse_date(fv_s) if fv_s else None
            configurado_mes = bool(fc or fv)
        elif base_fc and base_fc.strftime('%Y-%m') == mes_ym:
            fc = base_fc
            fv = base_fv
            configurado_mes = True
    else:
        fc = base_fc
        fv = base_fv
        configurado_mes = bool(fc or fv)

    # Calcular sugerencia para el mes seleccionado en base al último cierre/vencimiento conocido
    sug_fc = ''
    sug_fv = ''
    target_ym = mes_ym if (mes_ym and re.match(r'^\d{4}-\d{2}$', str(mes_ym))) else timezone.localdate().strftime('%Y-%m')
    try:
        ty, tm = [int(x) for x in target_ym.split('-')[:2]]
        ref_fc = fc or base_fc
        ref_fv = fv or base_fv
        if ref_fc:
            last_d = calendar.monthrange(ty, tm)[1]
            sug_fc = date(ty, tm, min(ref_fc.day, last_d)).strftime('%Y-%m-%d')
        if ref_fv:
            # Si el vencimiento suele caer en los primeros días del mes siguiente al cierre:
            if ref_fc and ref_fv.day < ref_fc.day:
                vy_str, vm_str = shift_ym(target_ym, 1).split('-')[:2]
                vy, vm = int(vy_str), int(vm_str)
            else:
                vy, vm = ty, tm
            last_vd = calendar.monthrange(vy, vm)[1]
            sug_fv = date(vy, vm, min(ref_fv.day, last_vd)).strftime('%Y-%m-%d')
    except Exception:
        pass

    return {
        'fecha_cierre': fc.strftime('%Y-%m-%d') if fc else '',
        'fecha_vencimiento': fv.strftime('%Y-%m-%d') if fv else '',
        'fecha_cierre_str': fc.strftime('%d/%m') if fc else '',
        'fecha_vencimiento_str': fv.strftime('%d/%m') if fv else '',
        'fechas_configuradas_mes': configurado_mes,
        'vence_en_mes': bool(fv and mes_ym and fv.strftime('%Y-%m') == str(mes_ym)),
        'sugerencia_cierre': sug_fc,
        'sugerencia_vencimiento': sug_fv,
    }


def get_local_dt(dt):
    if not dt:
        return timezone.localtime(timezone.now())
    if isinstance(dt, datetime):
        return timezone.localtime(dt) if timezone.is_aware(dt) else dt
    return datetime.combine(dt, datetime.min.time())


def get_local_ym(dt):
    return get_local_dt(dt).strftime('%Y-%m')


def shift_ym(ym_str, delta_months):
    """Suma o resta meses a un string 'YYYY-MM'."""
    try:
        y, m = [int(x) for x in ym_str.split('-')[:2]]
        total_m = (y * 12 + (m - 1)) + delta_months
        ny = total_m // 12
        nm = (total_m % 12) + 1
        return f"{ny:04d}-{nm:02d}"
    except (ValueError, TypeError, AttributeError):
        return ym_str


def format_mes_label(ym_str):
    """Convierte '2026-11' en 'Noviembre 2026'."""
    if not ym_str or ym_str == 'todos':
        return 'Todos los meses'
    try:
        y, m = [int(x) for x in ym_str.split('-')[:2]]
        if 1 <= m <= 12:
            return f"{MESES_ES[m]} {y}"
    except (ValueError, TypeError, AttributeError):
        pass
    return ym_str


def add_months_datetime(dt, months):
    """Suma `months` meses a un datetime preservando hora y ajustando el día al fin de mes."""
    if not months:
        return dt
    total_m = (dt.year * 12 + (dt.month - 1)) + months
    ny = total_m // 12
    nm = (total_m % 12) + 1
    last_day = calendar.monthrange(ny, nm)[1]
    nd = min(dt.day, last_day)
    return dt.replace(year=ny, month=nm, day=nd)


def get_fecha_cierre_for_ym(c_obj, target_ym):
    """
    Obtiene la fecha de cierre (`date`) de la tarjeta `c_obj` para el mes `target_ym` ('YYYY-MM').
    1) Si `c_obj.fechas_por_mes` tiene `fecha_cierre` configurada en `target_ym`, usa esa fecha exacta.
    2) Si no, proyecta el día de cierre habitual de la tarjeta (`c_obj.fecha_cierre` o el último cierre
       configurado en `fechas_por_mes`) dentro del año/mes `target_ym`.
    """
    if not c_obj or not target_ym or not re.match(r'^\d{4}-\d{2}$', str(target_ym)):
        return None

    fechas_map = getattr(c_obj, 'fechas_por_mes', None) or {}
    if isinstance(fechas_map, dict) and target_ym in fechas_map:
        fc_raw = ((fechas_map.get(target_ym) or {}).get('fecha_cierre') or '').strip()
        fc_parsed = parse_date(fc_raw) if fc_raw else None
        if fc_parsed:
            return fc_parsed

    ref_fc = getattr(c_obj, 'fecha_cierre', None)
    if not ref_fc and isinstance(fechas_map, dict):
        for ym_k in sorted(fechas_map.keys(), reverse=True):
            fc_s = ((fechas_map.get(ym_k) or {}).get('fecha_cierre') or '').strip()
            fc_cand = parse_date(fc_s) if fc_s else None
            if fc_cand:
                ref_fc = fc_cand
                break

    if ref_fc:
        try:
            ty, tm = [int(x) for x in target_ym.split('-')[:2]]
            last_d = calendar.monthrange(ty, tm)[1]
            return date(ty, tm, min(ref_fc.day, last_d))
        except Exception:
            return ref_fc

    return None


def tarjeta_vence_mismo_mes(c_obj, target_ym, fc=None):
    """
    Determina si la tarjeta `c_obj` vence dentro del MISMO mes que cierra (ej. Bna_Visa: cierra 05/11 y vence 18/11;
    cierra 10/12 y vence 23/12) vs al mes siguiente del cierre (ej. Macro_Visa: cierra 19/11 y vence 05/12).
    """
    if not c_obj:
        return False
    fechas_map = getattr(c_obj, 'fechas_por_mes', None) or {}
    fv = None
    if isinstance(fechas_map, dict) and target_ym in fechas_map:
        fv_s = ((fechas_map.get(target_ym) or {}).get('fecha_vencimiento') or '').strip()
        fv = parse_date(fv_s) if fv_s else None

    if fc and fv:
        return (fv.year == fc.year and fv.month == fc.month and fv >= fc)

    # Fallback al par (cierre, vencimiento) más reciente de la tarjeta
    ref_fc = getattr(c_obj, 'fecha_cierre', None)
    ref_fv = getattr(c_obj, 'fecha_vencimiento', None)
    if (not ref_fc or not ref_fv) and isinstance(fechas_map, dict):
        for ym_k in sorted(fechas_map.keys(), reverse=True):
            entry = fechas_map.get(ym_k) or {}
            c_cand = parse_date((entry.get('fecha_cierre') or '').strip()) if entry.get('fecha_cierre') else None
            v_cand = parse_date((entry.get('fecha_vencimiento') or '').strip()) if entry.get('fecha_vencimiento') else None
            if c_cand and v_cand:
                ref_fc, ref_fv = c_cand, v_cand
                break

    if ref_fc and ref_fv:
        return (ref_fv.year == ref_fc.year and ref_fv.month == ref_fc.month and ref_fv >= ref_fc)
    return False


def calcular_imputacion_tarjeta(g, c_obj=None, cuota1_map=None):
    """
    Determina a qué mes de resumen (`mes_resumen_ym`) pasa un gasto con tarjeta según su cierre y vencimiento:
    - Si `g.es_ajuste_tarjeta` es True (impuestos/diferencia al pagar resumen): queda en `get_local_ym(g.fecha)`.
    - Si la tarjeta vence en el MISMO mes que cierra (ej. Bna_Visa: cierra 05/11 y vence 18/11):
        * Compra ANTES o EL DÍA del cierre (`<= fc`): vence en el mismo mes (`offset_base = 0`, ej. 18/11).
        * Compra DESPUÉS del cierre (`> fc`, ej. 16/11): entra en el cierre del mes siguiente (10/12) y vence en Diciembre (`offset_base = 1`, ej. 23/12).
    - Si la tarjeta vence al MES SIGUIENTE del cierre (ej. Macro_Visa: cierra 19/11 y vence 05/12):
        * Compra ANTES o EL DÍA del cierre (`<= fc`): vence al mes siguiente (`offset_base = 1`, Diciembre).
        * Compra DESPUÉS del cierre (`> fc`): vence al mes subsiguiente (`offset_base = 2`, Enero).
    """
    dt_g = get_local_dt(g.fecha)
    if getattr(g, 'es_ajuste_tarjeta', False):
        ym = dt_g.strftime('%Y-%m')
        return {
            'compra_dt': dt_g,
            'compra_ym': ym,
            'mes_resumen_ym': ym,
            'es_post_cierre': False,
            'fecha_cierre_compra': None,
        }

    cuenta = c_obj or getattr(g, 'cuenta_bancaria', None)
    k = max(1, int(getattr(g, 'cuota_actual', 1) or 1))
    grp = getattr(g, 'grupo_cuotas_uid', '') or ''
    if grp and cuota1_map and grp in cuota1_map:
        g_base = cuota1_map[grp]
        k_base = max(1, int(getattr(g_base, 'cuota_actual', 1) or 1))
        compra_dt = get_local_dt(g_base.fecha)
        rel_k = max(0, k - k_base)
    else:
        compra_dt = dt_g
        rel_k = 0

    compra_ym = compra_dt.strftime('%Y-%m')
    fc = get_fecha_cierre_for_ym(cuenta, compra_ym)
    mismo_mes = tarjeta_vence_mismo_mes(cuenta, compra_ym, fc=fc)
    base_shift = 0 if mismo_mes else 1

    if fc and compra_dt.date() > fc:
        es_post_cierre = True
        offset_base = base_shift + 1
    else:
        es_post_cierre = False
        offset_base = base_shift

    mes_resumen_ym = shift_ym(compra_ym, offset_base + rel_k)
    return {
        'compra_dt': compra_dt,
        'compra_ym': compra_ym,
        'mes_resumen_ym': mes_resumen_ym,
        'es_post_cierre': es_post_cierre,
        'fecha_cierre_compra': fc,
    }


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
        user_cuentas = list(CuentaBancaria.objects.filter(usuario=user).order_by('-es_favorita', 'nombre'))
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
                        'es_favorita': bool(c.es_favorita),
                        'balance': 0.0,
                        'icon': 'card' if c.tipo == 'tarjeta' else ('cash' if c.tipo == 'efectivo' else 'wallet'),
                        'icon_class': 'macro' if c.tipo == 'tarjeta' else ('cash' if c.tipo == 'efectivo' else 'mp'),
                        'is_system': False,
                        **serialize_cuenta_fechas(c),
                    }
                    for c in user_cuentas
                ],
            },
            'categorias_disponibles': categorias_disponibles,
            'personas_disponibles': personas_disponibles,
            'cuentas_disponibles': [
                {
                    'id': c.id,
                    'nombre': c.nombre,
                    'tipo': c.tipo,
                    'subtitle': c.subtitulo_display,
                    'es_favorita': bool(c.es_favorita),
                    'balance': 0.0,
                    **serialize_cuenta_fechas(c),
                }
                for c in user_cuentas
            ],
        })

    # Recopilar movimientos del presupuesto seleccionado
    all_gastos = list(presupuesto.gastos.select_related('categoria', 'cuenta_bancaria').order_by('-fecha', '-id'))
    all_ingresos = list(presupuesto.ingresos.select_related('cuenta_bancaria').order_by('-fecha', '-id'))
    all_transferencias = list(
        presupuesto.transferencias_fondos.select_related('origen_cuenta', 'destino_cuenta').order_by('-fecha', '-id')
    )

    hoy_ym = hoy.strftime('%Y-%m')
    mes_param = (request.GET.get('mes') or '').strip()

    cuota1_por_grupo = {}
    for g in all_gastos:
        if g.grupo_cuotas_uid:
            prev_g = cuota1_por_grupo.get(g.grupo_cuotas_uid)
            if prev_g is None or (g.cuota_actual or 1) < (prev_g.cuota_actual or 1):
                cuota1_por_grupo[g.grupo_cuotas_uid] = g
    g_imputaciones = {}
    for g in all_gastos:
        if g.metodo_pago == 'tarjeta':
            g_imputaciones[g.id] = calcular_imputacion_tarjeta(
                g,
                c_obj=g.cuenta_bancaria,
                cuota1_map=cuota1_por_grupo,
            )

    # Selector de mes para presupuestos abiertos (y resumen por mes para tarjetas)
    meses_set = {
        shift_ym(hoy_ym, -1),
        hoy_ym,
        shift_ym(hoy_ym, 1),
        shift_ym(hoy_ym, 2),
    }
    for g in all_gastos:
        meses_set.add(get_local_ym(g.fecha))
        if g.id in g_imputaciones:
            meses_set.add(g_imputaciones[g.id]['mes_resumen_ym'])
            meses_set.add(g_imputaciones[g.id]['compra_ym'])
    for i in all_ingresos:
        meses_set.add(get_local_ym(i.fecha))
    for t in all_transferencias:
        meses_set.add(get_local_ym(t.fecha))

    if presupuesto.tipo == 'abierto':
        if mes_param == 'todos':
            mes_seleccionado = 'todos'
        elif re.match(r'^\d{4}-\d{2}$', mes_param):
            mes_seleccionado = mes_param
            meses_set.add(mes_seleccionado)
        else:
            mes_seleccionado = hoy_ym
    else:
        if re.match(r'^\d{4}-\d{2}$', mes_param):
            mes_seleccionado = mes_param
            meses_set.add(mes_seleccionado)
        else:
            mes_seleccionado = 'todos'

    meses_ordenados = sorted(list(meses_set))
    meses_disponibles = [
        {'ym': ym, 'label': format_mes_label(ym)}
        for ym in meses_ordenados
    ]

    if presupuesto.tipo == 'abierto' and mes_seleccionado != 'todos':
        gastos = [g for g in all_gastos if get_local_ym(g.fecha) == mes_seleccionado]
        gastos_tarjeta_comprados_mes = [
            g for g in all_gastos
            if g.metodo_pago == 'tarjeta'
            and not g.es_ajuste_tarjeta
            and (
                not g.grupo_cuotas_uid
                or (cuota1_por_grupo.get(g.grupo_cuotas_uid) and cuota1_por_grupo[g.grupo_cuotas_uid].id == g.id)
            )
            and g_imputaciones[g.id]['compra_ym'] == mes_seleccionado
        ]
        ingresos = [i for i in all_ingresos if get_local_ym(i.fecha) == mes_seleccionado]
        transferencias = [t for t in all_transferencias if get_local_ym(t.fecha) == mes_seleccionado]
    else:
        gastos = all_gastos
        gastos_tarjeta_comprados_mes = []
        ingresos = all_ingresos
        transferencias = all_transferencias

    mes_ref_ym = mes_seleccionado if (mes_seleccionado and mes_seleccionado != 'todos') else hoy_ym
    mes_ant_ym = shift_ym(mes_ref_ym, -1)
    mes_sig_ym = shift_ym(mes_ref_ym, 1)
    mes_subsig_ym = shift_ym(mes_ref_ym, 2)

    total_gastos_all = sum((g.monto for g in gastos), Decimal('0'))
    total_gastos_comp = sum((g.monto for g in gastos if g.metodo_pago != 'tarjeta'), Decimal('0'))
    total_tarjeta = sum((g.monto for g in gastos if g.metodo_pago == 'tarjeta'), Decimal('0'))
    total_ingresos = sum((i.monto for i in ingresos), Decimal('0'))
    saldo_efectivo = presupuesto.saldo_efectivo
    saldo_transferencia = presupuesto.saldo_transferencia
    disponible = presupuesto.monto_total_con_ingresos()

    def build_pago_tarjeta_detalle(g):
        if g.metodo_pago == 'tarjeta':
            return None
        desc = g.descripcion or ''
        nom = g.nombre or ''
        if not (desc.startswith('Pago de resumen de ') or nom.lower().startswith('pago tarjeta ')):
            return None

        # Extraer nombre de tarjeta y período
        card_name = ''
        m_card = re.search(r'Pago de resumen de ([^·(\[\n]+)', desc)
        if m_card:
            card_name = m_card.group(1).strip()
        if not card_name:
            m_nom = re.match(r'Pago tarjeta\s+(.+?)(?:\s*\([^)]+\))?$', nom, flags=re.IGNORECASE)
            if m_nom:
                card_name = m_nom.group(1).strip()
        if not card_name:
            return None

        m_per = re.search(r'\[Periodo:(\d{4}-\d{2})\]', desc)
        target_ym = m_per.group(1) if m_per else get_local_ym(g.fecha)

        consumos_periodo = [
            x for x in all_gastos
            if x.metodo_pago == 'tarjeta'
            and not x.es_ajuste_tarjeta
            and x.cuenta_bancaria
            and x.cuenta_bancaria.nombre.lower() == card_name.lower()
            and g_imputaciones.get(x.id, {}).get('mes_resumen_ym') == target_ym
        ]
        consumos_periodo.sort(key=lambda x: get_local_dt(x.fecha))
        subtotal_consumos = sum((x.monto for x in consumos_periodo), Decimal('0'))
        diferencia = g.monto - subtotal_consumos

        return {
            'tarjeta_nombre': card_name,
            'mes_resumen': target_ym,
            'mes_resumen_label': format_mes_label(target_ym),
            'monto_pagado': float(g.monto),
            'subtotal_consumos': float(subtotal_consumos),
            'diferencia': float(diferencia),
            'consumos': [
                {
                    'id': x.id,
                    'nombre': x.nombre,
                    'monto': float(x.monto),
                    'fecha_str': get_local_dt(x.fecha).strftime('%d/%m'),
                    'cuota_actual': x.cuota_actual or 1,
                    'cuotas_totales': x.cuotas_totales or 1,
                }
                for x in consumos_periodo
            ],
        }

    def serialize_gasto_mov_dict(g):
        icon, tone = resolve_gasto_icon_tone(g)
        cat_label = g.categoria.nombre if g.categoria else 'Sin categoría'
        imp = g_imputaciones.get(g.id)
        parts_detail = [cat_label]
        if g.cuenta_bancaria:
            parts_detail.append(g.cuenta_bancaria.nombre)
        elif g.metodo_pago == 'tarjeta':
            parts_detail.append('Tarjeta')
        elif g.metodo_pago == 'efectivo':
            parts_detail.append('Efectivo')
        if g.cuotas_totales and g.cuotas_totales > 1:
            parts_detail.append(f"🗓️ Cuota {g.cuota_actual}/{g.cuotas_totales}")
        if imp and not g.es_ajuste_tarjeta:
            res_lbl = format_mes_label(imp['mes_resumen_ym'])
            post_lbl = ' (post-cierre)' if imp['es_post_cierre'] else ''
            parts_detail.append(f"➔ {res_lbl}{post_lbl}")
        if g.persona:
            parts_detail.append(f"👤 {g.persona}")
        parts_detail.append(format_fecha_humana(imp['compra_dt'] if (imp and not g.es_ajuste_tarjeta) else g.fecha))

        dt_local = timezone.localtime(g.fecha) if timezone.is_aware(g.fecha) else g.fecha
        return {
            '_sort_dt': dt_local,
            'uid': f"gasto-{g.id}",
            'id': g.id,
            'tipo_movimiento': 'gasto',
            'title': g.nombre,
            'detail': ' · '.join([p for p in parts_detail if p]),
            'categoria': cat_label,
            'categoria_id': g.categoria_id or '',
            'metodo_pago': g.metodo_pago,
            'cuenta': g.cuenta_bancaria.nombre if g.cuenta_bancaria else ('Efectivo' if g.metodo_pago == 'efectivo' else ''),
            'cuenta_bancaria': g.cuenta_bancaria.nombre if g.cuenta_bancaria else '',
            'persona': g.persona or '',
            'descripcion': g.descripcion or '',
            'amount': -float(g.monto),
            'raw_monto': float(g.monto),
            'es_rapido': bool(g.es_rapido),
            'cuota_actual': g.cuota_actual or 1,
            'cuotas_totales': g.cuotas_totales or 1,
            'grupo_cuotas_uid': g.grupo_cuotas_uid or '',
            'es_ajuste_tarjeta': bool(g.es_ajuste_tarjeta),
            'mes_resumen': imp['mes_resumen_ym'] if imp else '',
            'mes_resumen_label': format_mes_label(imp['mes_resumen_ym']) if imp else '',
            'compra_ym': imp['compra_ym'] if imp else get_local_ym(g.fecha),
            'es_post_cierre': bool(imp['es_post_cierre']) if imp else False,
            'pago_tarjeta_detalle': build_pago_tarjeta_detalle(g),
            'is_transfer': False,
            'icon': icon,
            'tone': tone,
            'fecha_iso': dt_local.strftime('%Y-%m-%d'),
            'fecha_hora_iso': dt_local.strftime('%Y-%m-%dT%H:%M'),
        }

    # Armar lista unificada de movimientos
    raw_movs = []
    for g in gastos:
        raw_movs.append(serialize_gasto_mov_dict(g))

    compras_tarjeta_mes_origen = []
    total_origen_pasa_sig = Decimal('0')
    total_origen_pasa_subsig = Decimal('0')
    for g in gastos_tarjeta_comprados_mes:
        d_item = serialize_gasto_mov_dict(g)
        d_item.pop('_sort_dt', None)
        compras_tarjeta_mes_origen.append(d_item)
        imp = g_imputaciones.get(g.id)
        if imp:
            if imp['es_post_cierre']:
                total_origen_pasa_subsig += g.monto
            else:
                total_origen_pasa_sig += g.monto

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
            'tipo_ingreso': i.tipo_ingreso,
            'cuenta': i.cuenta_bancaria.nombre if i.cuenta_bancaria else ('Efectivo' if i.tipo_ingreso == 'efectivo' else ''),
            'cuenta_bancaria': i.cuenta_bancaria.nombre if i.cuenta_bancaria else '',
            'persona': '',
            'descripcion': i.descripcion or '',
            'amount': float(i.monto),
            'raw_monto': float(i.monto),
            'es_rapido': bool(i.es_rapido),
            'is_transfer': False,
            'icon': 'cash' if i.tipo_ingreso == 'efectivo' else 'swap',
            'tone': 'green',
            'fecha_iso': dt_local.strftime('%Y-%m-%d'),
            'fecha_hora_iso': dt_local.strftime('%Y-%m-%dT%H:%M'),
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
            'origen_tipo': t.origen_tipo,
            'origen_cuenta': t.origen_cuenta.nombre if t.origen_cuenta else '',
            'destino_tipo': t.destino_tipo,
            'destino_cuenta': t.destino_cuenta.nombre if t.destino_cuenta else '',
            'nota': t.nota or '',
            'persona': '',
            'amount': float(t.monto),
            'raw_monto': float(t.monto),
            'es_rapido': False,
            'is_transfer': True,
            'icon': 'swap',
            'tone': 'blue',
            'fecha_iso': dt_local.strftime('%Y-%m-%d'),
            'fecha_hora_iso': dt_local.strftime('%Y-%m-%dT%H:%M'),
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

    # Calcular saldos por CuentaBancaria en este presupuesto (liquidez acumulada total, consumos tarjeta del período)
    def init_cuenta_stat(c_obj, nombre):
        return {
            'obj': c_obj,
            'nombre': nombre,
            'ingresos': Decimal('0'),
            'gastos_liquidos': Decimal('0'),
            'gastos_tarjeta': Decimal('0'),
            'consumos_mes_actual': [],
            'consumos_mes_anterior': [],
            'consumos_mes_siguiente': [],
            'consumos_mes_subsiguiente': [],
            'total_mes_actual': Decimal('0'),
            'total_mes_anterior': Decimal('0'),
            'total_mes_siguiente': Decimal('0'),
            'total_mes_subsiguiente': Decimal('0'),
        }

    cuentas_stats = {}
    for c in user_cuentas:
        cuentas_stats[c.nombre.lower()] = init_cuenta_stat(c, c.nombre)

    for i in all_ingresos:
        if i.cuenta_bancaria:
            key = i.cuenta_bancaria.nombre.lower()
            if key not in cuentas_stats:
                cuentas_stats[key] = init_cuenta_stat(i.cuenta_bancaria, i.cuenta_bancaria.nombre)
            cuentas_stats[key]['ingresos'] += i.monto

    tarjeta_sin_cuenta = Decimal('0')
    for g in all_gastos:
        imp = g_imputaciones.get(g.id) if g.metodo_pago == 'tarjeta' else None
        g_eff_ym = imp['mes_resumen_ym'] if imp else get_local_ym(g.fecha)
        in_vista = (presupuesto.tipo != 'abierto' or mes_seleccionado == 'todos' or g_eff_ym == mes_seleccionado)
        if g.cuenta_bancaria:
            key = g.cuenta_bancaria.nombre.lower()
            if key not in cuentas_stats:
                cuentas_stats[key] = init_cuenta_stat(g.cuenta_bancaria, g.cuenta_bancaria.nombre)
            if g.metodo_pago == 'tarjeta':
                if in_vista:
                    cuentas_stats[key]['gastos_tarjeta'] += g.monto
                dt_compra_ref = imp['compra_dt'] if (imp and not g.es_ajuste_tarjeta) else get_local_dt(g.fecha)
                item_tarj = {
                    'id': g.id,
                    'nombre': g.nombre,
                    'monto': float(g.monto),
                    'fecha_str': dt_compra_ref.strftime('%d/%m'),
                    'cuota_actual': g.cuota_actual or 1,
                    'cuotas_totales': g.cuotas_totales or 1,
                    'es_ajuste_tarjeta': bool(g.es_ajuste_tarjeta),
                    'es_post_cierre': bool(imp['es_post_cierre']) if imp else False,
                    'mes_resumen_ym': g_eff_ym,
                    'mes_resumen_label': format_mes_label(g_eff_ym),
                }
                if g_eff_ym == mes_ref_ym or (presupuesto.tipo != 'abierto' and mes_seleccionado == 'todos'):
                    cuentas_stats[key]['consumos_mes_actual'].append(item_tarj)
                    cuentas_stats[key]['total_mes_actual'] += g.monto
                if g_eff_ym == mes_ant_ym:
                    cuentas_stats[key]['consumos_mes_anterior'].append(item_tarj)
                    cuentas_stats[key]['total_mes_anterior'] += g.monto
                if g_eff_ym == mes_sig_ym:
                    cuentas_stats[key]['consumos_mes_siguiente'].append(item_tarj)
                    cuentas_stats[key]['total_mes_siguiente'] += g.monto
                if g_eff_ym == mes_subsig_ym:
                    cuentas_stats[key]['consumos_mes_subsiguiente'].append(item_tarj)
                    cuentas_stats[key]['total_mes_subsiguiente'] += g.monto
            else:
                cuentas_stats[key]['gastos_liquidos'] += g.monto
        elif g.metodo_pago == 'tarjeta' and in_vista:
            tarjeta_sin_cuenta += g.monto

    for t in all_transferencias:
        if t.origen_cuenta:
            key = t.origen_cuenta.nombre.lower()
            if key not in cuentas_stats:
                cuentas_stats[key] = init_cuenta_stat(t.origen_cuenta, t.origen_cuenta.nombre)
            cuentas_stats[key]['gastos_liquidos'] += t.monto
        if t.destino_cuenta:
            key = t.destino_cuenta.nombre.lower()
            if key not in cuentas_stats:
                cuentas_stats[key] = init_cuenta_stat(t.destino_cuenta, t.destino_cuenta.nombre)
            cuentas_stats[key]['ingresos'] += t.monto

    tarjetas_pagadas_mes = set()
    for g in all_gastos:
        if g.metodo_pago != 'tarjeta':
            p_det = build_pago_tarjeta_detalle(g)
            if p_det and (p_det['mes_resumen'] == mes_ref_ym or get_local_ym(g.fecha) == mes_ref_ym):
                tarjetas_pagadas_mes.add(p_det['tarjeta_nombre'].lower())

    cuentas_items = []
    for key, st in cuentas_stats.items():
        c_obj = st['obj']
        saldo_liq = st['ingresos'] - st['gastos_liquidos']
        gas_tarj = st['gastos_tarjeta']
        c_tipo = resolve_cuenta_tipo(c_obj, saldo_liq, gas_tarj)
        sub = 'Tarjeta de crédito' if c_tipo == 'tarjeta' else (c_obj.subtitulo_display if c_obj else 'Billetera virtual')

        if c_tipo == 'tarjeta':
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

        is_fav = bool(c_obj.es_favorita) if c_obj else False
        fechas_mes_target = mes_seleccionado if (presupuesto.tipo == 'abierto' and mes_seleccionado != 'todos') else None
        fechas_ser = serialize_cuenta_fechas(c_obj, mes_ym=fechas_mes_target)
        is_paid_mes = (st['nombre'].lower() in tarjetas_pagadas_mes) if c_tipo == 'tarjeta' else False
        fechas_ser['pagada_en_mes'] = is_paid_mes
        if is_paid_mes:
            fechas_ser['vence_en_mes'] = False

        cuentas_items.append({
            'id': c_obj.id if c_obj else 0,
            'name': st['nombre'],
            'subtitle': sub,
            'tipo': c_tipo,
            'es_favorita': is_fav,
            'balance': bal,
            'gastos_tarjeta': float(gas_tarj),
            'resumen_tarjeta': {
                'mes_actual_ym': mes_ref_ym,
                'mes_actual_label': format_mes_label(mes_ref_ym),
                'total_mes_actual': float(st['total_mes_actual']),
                'consumos_mes_actual': st['consumos_mes_actual'],
                'mes_anterior_ym': mes_ant_ym,
                'mes_anterior_label': format_mes_label(mes_ant_ym),
                'total_mes_anterior': float(st['total_mes_anterior']),
                'consumos_mes_anterior': st['consumos_mes_anterior'],
                'mes_siguiente_ym': mes_sig_ym,
                'mes_siguiente_label': format_mes_label(mes_sig_ym),
                'total_mes_siguiente': float(st['total_mes_siguiente']),
                'consumos_mes_siguiente': st['consumos_mes_siguiente'],
                'mes_subsiguiente_ym': mes_subsig_ym,
                'mes_subsiguiente_label': format_mes_label(mes_subsig_ym),
                'total_mes_subsiguiente': float(st['total_mes_subsiguiente']),
                'consumos_mes_subsiguiente': st['consumos_mes_subsiguiente'],
            },
            'icon': icon_name,
            'icon_class': icon_cls,
            'is_system': False,
            **fechas_ser,
        })

    # Ordenar cuentas:
    # 1) Favorita arriba de todo
    # 2) Las que tienen saldo positivo arriba (ordenadas de mayor a menor saldo)
    # 3) Las que tienen movimiento / tarjeta
    # 4) Resto por orden alfabético
    def sort_key_cuenta(x):
        fav_rank = 0 if x.get('es_favorita') else 1
        bal = x.get('balance', 0.0)
        gt = x.get('gastos_tarjeta', 0.0)
        if bal > 0:
            bal_rank = 0
        elif bal != 0 or gt != 0:
            bal_rank = 1
        else:
            bal_rank = 2
        return (fav_rank, bal_rank, -bal, -abs(bal), (x.get('name') or x.get('nombre') or '').lower())

    cuentas_items.sort(key=sort_key_cuenta)

    cuentas_disponibles_list = [
        {
            'id': item['id'],
            'nombre': item['name'],
            'tipo': item['tipo'],
            'subtitle': item['subtitle'],
            'es_favorita': item['es_favorita'],
            'balance': item['balance'],
            'fecha_cierre': item.get('fecha_cierre', ''),
            'fecha_vencimiento': item.get('fecha_vencimiento', ''),
            'fecha_cierre_str': item.get('fecha_cierre_str', ''),
            'fecha_vencimiento_str': item.get('fecha_vencimiento_str', ''),
            'fechas_configuradas_mes': item.get('fechas_configuradas_mes', False),
            'sugerencia_cierre': item.get('sugerencia_cierre', ''),
            'sugerencia_vencimiento': item.get('sugerencia_vencimiento', ''),
        }
        for item in cuentas_items
    ]

    # Agregar Efectivo disponible como cuenta del presupuesto
    cuentas_items.append({
        'id': -1,
        'name': 'Efectivo',
        'subtitle': 'Dinero disponible',
        'tipo': 'efectivo',
        'es_favorita': False,
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
            'es_favorita': False,
            'balance': -float(total_tarjeta),
            'gastos_tarjeta': float(total_tarjeta),
            'icon': 'card',
            'icon_class': 'macro',
            'is_system': True,
        })

    if presupuesto.tipo == 'abierto' and mes_seleccionado != 'todos':
        mes_label = format_mes_label(mes_seleccionado).upper()
    elif presupuesto.tipo == 'abierto' and mes_seleccionado == 'todos':
        mes_label = 'TODOS LOS MESES'
    else:
        mes_nombre = MESES_ES[presupuesto.fecha_inicio.month].upper() if 1 <= presupuesto.fecha_inicio.month <= 12 else ''
        mes_label = f"{mes_nombre} {presupuesto.fecha_inicio.year}".strip()

    presupuesto_data = serialize_presupuesto_item(presupuesto, user, hoy)
    presupuesto_data['mes_label'] = mes_label
    presupuesto_data['total_gastos_all'] = float(total_gastos_all)
    presupuesto_data['ingresos_periodo'] = float(total_ingresos)
    presupuesto_data['gastos_computables_periodo'] = float(total_gastos_comp)
    presupuesto_data['total_tarjeta_periodo'] = float(total_tarjeta)

    mes_info = None
    if presupuesto.tipo == 'abierto':
        mes_info = {
            'mes_seleccionado': mes_seleccionado,
            'mes_label': format_mes_label(mes_seleccionado),
            'mes_anterior': mes_ant_ym,
            'mes_anterior_label': format_mes_label(mes_ant_ym),
            'mes_siguiente': mes_sig_ym,
            'mes_siguiente_label': format_mes_label(mes_sig_ym),
            'mes_subsiguiente': mes_subsig_ym,
            'mes_subsiguiente_label': format_mes_label(mes_subsig_ym),
            'meses_disponibles': meses_disponibles,
            'ingresos_mes': float(total_ingresos),
            'gastos_computables_mes': float(total_gastos_comp),
            'gastos_tarjeta_mes': float(total_tarjeta),
            'compras_tarjeta_mes_origen': compras_tarjeta_mes_origen,
            'total_origen_pasa_siguiente': float(total_origen_pasa_sig),
            'total_origen_pasa_subsiguiente': float(total_origen_pasa_subsig),
        }

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
        'mes_info': mes_info,
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
        'cuentas_disponibles': cuentas_disponibles_list,
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
                    'cuenta_bancaria': i.cuenta_bancaria.nombre if i.cuenta_bancaria else '',
                    'tarjeta_id': i.tarjeta_prestamo_id or '',
                    'tasa_interes': float(i.tasa_interes or tasa_default),
                    'persona': '',
                    'amount': float(i.monto),
                    'raw_monto': float(i.monto),
                    'monto_proximo_mes': prox,
                    'interes_monto': inter,
                    'es_rapido': bool(i.es_rapido),
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
                    'raw_monto': float(i.monto),
                    'es_rapido': bool(i.es_rapido),
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
                'tarjeta_id': d.tarjeta_id,
                'concepto': d.concepto,
                'persona': '',
                'amount': -float(d.monto),
                'raw_monto': float(d.monto),
                'es_rapido': False,
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
    es_fav = bool(data.get('es_favorita', False))
    if es_fav:
        CuentaBancaria.objects.filter(usuario=request.api_user, es_favorita=True).update(es_favorita=False)

    fc_raw = (data.get('fecha_cierre') or '').strip()
    fv_raw = (data.get('fecha_vencimiento') or '').strip()
    fecha_cierre_val = parse_date(fc_raw) if fc_raw else None
    fecha_vencimiento_val = parse_date(fv_raw) if fv_raw else None
    mes_ym = (data.get('mes') or '').strip()
    if not re.match(r'^\d{4}-\d{2}$', mes_ym):
        if fecha_cierre_val:
            mes_ym = fecha_cierre_val.strftime('%Y-%m')
        else:
            mes_ym = timezone.localdate().strftime('%Y-%m')

    cuenta_id = data.get('id') or data.get('cuenta_id')
    cuenta = None
    if cuenta_id and str(cuenta_id).isdigit() and int(cuenta_id) > 0:
        cuenta = CuentaBancaria.objects.filter(id=int(cuenta_id), usuario=request.api_user).first()
    if not cuenta:
        cuenta = CuentaBancaria.objects.filter(usuario=request.api_user, nombre__iexact=nombre_clean).first()

    created = False
    if cuenta:
        cuenta.nombre = nombre_clean
        cuenta.tipo = tipo
        if 'es_favorita' in data:
            cuenta.es_favorita = es_fav
        if tipo == 'tarjeta':
            if 'fecha_cierre' in data:
                cuenta.fecha_cierre = fecha_cierre_val
            if 'fecha_vencimiento' in data:
                cuenta.fecha_vencimiento = fecha_vencimiento_val
            if 'fecha_cierre' in data or 'fecha_vencimiento' in data:
                f_map = dict(cuenta.fechas_por_mes or {})
                prev_entry = f_map.get(mes_ym) if isinstance(f_map.get(mes_ym), dict) else {}
                f_map[mes_ym] = {
                    'fecha_cierre': fecha_cierre_val.strftime('%Y-%m-%d') if fecha_cierre_val else ('' if 'fecha_cierre' in data else prev_entry.get('fecha_cierre', '')),
                    'fecha_vencimiento': fecha_vencimiento_val.strftime('%Y-%m-%d') if fecha_vencimiento_val else ('' if 'fecha_vencimiento' in data else prev_entry.get('fecha_vencimiento', '')),
                }
                cuenta.fechas_por_mes = f_map
        else:
            cuenta.fecha_cierre = None
            cuenta.fecha_vencimiento = None
        cuenta.save()
    else:
        # Si es la primera billetera del usuario, marcarla como favorita por defecto
        has_any = CuentaBancaria.objects.filter(usuario=request.api_user).exclude(tipo='tarjeta').exists()
        init_fechas_map = {}
        if tipo == 'tarjeta' and (fecha_cierre_val or fecha_vencimiento_val):
            init_fechas_map[mes_ym] = {
                'fecha_cierre': fecha_cierre_val.strftime('%Y-%m-%d') if fecha_cierre_val else '',
                'fecha_vencimiento': fecha_vencimiento_val.strftime('%Y-%m-%d') if fecha_vencimiento_val else '',
            }
        cuenta = CuentaBancaria.objects.create(
            usuario=request.api_user,
            nombre=nombre_clean,
            tipo=tipo,
            es_favorita=es_fav or (not has_any and tipo != 'tarjeta'),
            fecha_cierre=fecha_cierre_val if tipo == 'tarjeta' else None,
            fecha_vencimiento=fecha_vencimiento_val if tipo == 'tarjeta' else None,
            fechas_por_mes=init_fechas_map,
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
            'es_favorita': bool(cuenta.es_favorita),
            'subtitle': cuenta.subtitulo_display,
            **serialize_cuenta_fechas(cuenta, mes_ym=mes_ym),
        }
    }, status=201 if created else 200)


@csrf_exempt
@api_auth_required
@require_http_methods(["POST"])
def toggle_cuenta_favorita_api(request):
    """
    Marca o desmarca una CuentaBancaria como la billetera favorita del usuario.
    POST /api/cuentas/favorita/
    Body: {"id": 3, "nombre": "Mercado Pago"}
    """
    data = parse_request_data(request)
    cid = data.get('id') or data.get('cuenta_id')
    nombre_raw = (data.get('nombre') or '').strip()

    cuenta = None
    if cid and int(cid) > 0:
        cuenta = CuentaBancaria.objects.filter(id=cid, usuario=request.api_user).first()
    if not cuenta and nombre_raw:
        cuenta = CuentaBancaria.objects.filter(usuario=request.api_user, nombre__iexact=nombre_raw).first()
        if not cuenta:
            cuenta = CuentaBancaria.objects.create(
                usuario=request.api_user,
                nombre=nombre_raw[:60],
                tipo='billetera',
                es_favorita=False,
            )

    if not cuenta:
        return JsonResponse({'success': False, 'error': 'Cuenta no encontrada'}, status=404)

    nueva_fav = not cuenta.es_favorita
    CuentaBancaria.objects.filter(usuario=request.api_user).update(es_favorita=False)
    cuenta.es_favorita = nueva_fav
    cuenta.save()

    return JsonResponse({
        'success': True,
        'es_favorita': cuenta.es_favorita,
        'mensaje': f'⭐ {cuenta.nombre} marcada como billetera favorita' if cuenta.es_favorita else f'{cuenta.nombre} ya no es favorita',
        'cuenta': {
            'id': cuenta.id,
            'nombre': cuenta.nombre,
            'es_favorita': cuenta.es_favorita,
        }
    })


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

    raw_es_rapido = data.get('es_rapido')
    es_rapido = bool(
        raw_es_rapido in (True, 'true', 'True', 1, '1')
        or not nombre
        or (
            'fecha' not in data
            and 'categoria_nombre' not in data
            and not data.get('categoria_id')
            and not data.get('persona')
            and not data.get('cuenta_bancaria')
        )
    )
    # Si no se especificó nombre, asignar nombre automático secuencial
    if not nombre:
        es_rapido = True
        count_rapidos = Gasto.objects.filter(
            presupuesto=presupuesto
        ).filter(
            Q(nombre__icontains='rápido') | Q(nombre__icontains='rapido') | Q(nombre__startswith='⚡')
        ).count()
        nombre = f"⚡ Gasto rápido {count_rapidos + 1:02d}"
    elif es_rapido and not nombre.startswith('⚡'):
        nombre = f"⚡ {nombre}"

    # Categoría opcional (por ID o por nombre; si el nombre no existe, se crea automáticamente)
    categoria_id = data.get('categoria_id')
    categoria_nombre = (data.get('categoria_nombre') or '').strip()
    categoria = resolve_or_create_categoria(categoria_id, categoria_nombre)

    # Fecha y hora opcional
    fecha = parse_fecha_hora_input(data.get('fecha'))

    descripcion = (data.get('descripcion') or '').strip()
    metodo_pago = (data.get('metodo_pago') or 'efectivo').lower().strip()
    if metodo_pago not in ['efectivo', 'transferencia', 'tarjeta']:
        metodo_pago = 'efectivo'

    # Detectar automáticamente efectivo / transferencia en el concepto (cuando no se eligió explícitamente en el selector)
    cuenta_raw = (data.get('cuenta_bancaria') or '').strip()
    metodo_explicit = bool(data.get('metodo_pago_explicit'))
    metodo_det, cuenta_det = detectar_metodo_y_cuenta_desde_concepto(f"{nombre} {descripcion}", request.api_user)
    if metodo_det and not metodo_explicit and (es_rapido or not data.get('metodo_pago')):
        metodo_pago = metodo_det

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
    elif metodo_pago != 'efectivo' and cuenta_det:
        cuenta_bancaria = cuenta_det
    elif metodo_pago == 'transferencia' and not cuenta_raw:
        # Si eligió transferencia sin especificar cuenta, usar la billetera favorita si existe
        cuenta_bancaria = CuentaBancaria.objects.filter(
            usuario=request.api_user,
            es_favorita=True
        ).exclude(tipo='tarjeta').first()

    # Cuotas opcionales cuando es gasto con tarjeta (se generan automáticamente en los meses siguientes)
    try:
        cuotas_totales = int(data.get('cuotas_totales') or 1)
    except (ValueError, TypeError):
        cuotas_totales = 1
    cuotas_totales = max(1, min(48, cuotas_totales))
    try:
        cuota_inicial = int(data.get('cuota_inicial') or 1)
    except (ValueError, TypeError):
        cuota_inicial = 1
    cuota_inicial = max(1, min(cuotas_totales, cuota_inicial))
    modo_monto_cuotas = (data.get('modo_monto_cuotas') or 'cuota').strip().lower()
    es_ajuste_tarjeta = bool(data.get('es_ajuste_tarjeta', False))

    base_dt = fecha or timezone.localtime(timezone.now())
    if metodo_pago == 'tarjeta' and cuotas_totales > 1:
        if modo_monto_cuotas == 'total':
            monto_cuota = (monto / Decimal(cuotas_totales)).quantize(Decimal('0.01'))
        else:
            monto_cuota = monto
        grupo_uid = f"cuotas-{uuid.uuid4().hex[:12]}"
        base_nombre = re.sub(r'\s*\(Cuota\s+\d+/\d+\)\s*$', '', nombre, flags=re.IGNORECASE).strip()

        created_gastos = []
        for k in range(cuota_inicial, cuotas_totales + 1):
            dt_k = add_months_datetime(base_dt, k - cuota_inicial)
            g_k = Gasto(
                presupuesto=presupuesto,
                categoria=categoria,
                nombre=f"{base_nombre} (Cuota {k}/{cuotas_totales})"[:100],
                persona=persona,
                cuenta_bancaria=cuenta_bancaria,
                monto=monto_cuota,
                metodo_pago='tarjeta',
                descripcion=descripcion or None,
                fecha=dt_k,
                es_rapido=es_rapido if k == cuota_inicial else False,
                cuota_actual=k,
                cuotas_totales=cuotas_totales,
                grupo_cuotas_uid=grupo_uid,
                es_ajuste_tarjeta=False,
            )
            g_k.full_clean()
            g_k.save()
            created_gastos.append(g_k)
        gasto = created_gastos[0]
        cuotas_creadas_count = len(created_gastos)
    else:
        gasto = Gasto(
            presupuesto=presupuesto,
            categoria=categoria,
            nombre=nombre,
            persona=persona,
            cuenta_bancaria=cuenta_bancaria,
            monto=monto,
            metodo_pago=metodo_pago,
            descripcion=descripcion or None,
            fecha=base_dt,
            es_rapido=es_rapido,
            cuota_actual=1,
            cuotas_totales=1,
            grupo_cuotas_uid='',
            es_ajuste_tarjeta=es_ajuste_tarjeta if metodo_pago == 'tarjeta' else False,
        )
        gasto.full_clean()
        gasto.save()
        cuotas_creadas_count = 1

    presupuesto.refresh_from_db()

    imp_creado = calcular_imputacion_tarjeta(gasto, c_obj=cuenta_bancaria) if metodo_pago == 'tarjeta' else None
    if metodo_pago == 'tarjeta' and imp_creado and not gasto.es_ajuste_tarjeta:
        res_lbl = format_mes_label(imp_creado['mes_resumen_ym'])
        post_note = ' (post-cierre)' if imp_creado['es_post_cierre'] else ''
        if cuotas_totales > 1:
            if cuota_inicial > 1:
                msg_resp = f"Registradas cuotas {cuota_inicial} a {cuotas_totales} ({cuotas_creadas_count} restantes){post_note} · Cuota {cuota_inicial} pasa a {res_lbl}"
            else:
                msg_resp = f"Compra en {cuotas_totales} cuotas registrada{post_note} · Cuota 1 pasa a {res_lbl}"
        else:
            msg_resp = f"Gasto con tarjeta registrado{post_note} · Pasa a {res_lbl}"
    else:
        msg_resp = f"Gasto de {presupuesto.moneda} {gasto.monto} registrado exitosamente"

    return JsonResponse({
        'success': True,
        'mensaje': msg_resp,
        'cuotas_creadas': cuotas_creadas_count,
        'gasto': {
            'id': gasto.id,
            'nombre': gasto.nombre,
            'persona': gasto.persona,
            'cuenta_bancaria': gasto.cuenta_bancaria.nombre if gasto.cuenta_bancaria else None,
            'metodo_pago': gasto.metodo_pago,
            'monto': float(gasto.monto),
            'cuota_actual': gasto.cuota_actual,
            'cuotas_totales': gasto.cuotas_totales,
            'mes_resumen': imp_creado['mes_resumen_ym'] if imp_creado else '',
            'mes_resumen_label': format_mes_label(imp_creado['mes_resumen_ym']) if imp_creado else '',
            'es_post_cierre': bool(imp_creado['es_post_cierre']) if imp_creado else False,
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

    raw_es_rapido = data.get('es_rapido')
    es_rapido = bool(
        raw_es_rapido in (True, 'true', 'True', 1, '1')
        or not nombre
        or ('fecha' not in data and not data.get('cuenta_bancaria'))
    )
    # Si no se especificó nombre, asignar nombre automático secuencial
    if not nombre:
        es_rapido = True
        count_rapidos = Ingreso.objects.filter(
            presupuesto=presupuesto
        ).filter(
            Q(nombre__icontains='rápido') | Q(nombre__icontains='rapido') | Q(nombre__startswith='⚡')
        ).count()
        nombre = f"⚡ Ingreso rápido {count_rapidos + 1:02d}"
    elif es_rapido and not nombre.startswith('⚡'):
        nombre = f"⚡ {nombre}"

    tipo_ingreso = (data.get('tipo_ingreso') or 'transferencia').lower().strip()
    if tipo_ingreso not in ['transferencia', 'efectivo', 'sueldo']:
        tipo_ingreso = 'transferencia'

    cuenta_raw = (data.get('cuenta_bancaria') or '').strip()
    tipo_explicit = bool(data.get('tipo_ingreso_explicit'))
    metodo_det, cuenta_det = detectar_metodo_y_cuenta_desde_concepto(f"{nombre} {data.get('descripcion') or ''}", request.api_user)
    if metodo_det in ['efectivo', 'transferencia'] and not tipo_explicit and (es_rapido or not data.get('tipo_ingreso')):
        tipo_ingreso = metodo_det

    cuenta_bancaria = None
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
    elif tipo_ingreso != 'efectivo' and cuenta_det:
        cuenta_bancaria = cuenta_det
    elif tipo_ingreso != 'efectivo' and not cuenta_raw:
        cuenta_bancaria = CuentaBancaria.objects.filter(
            usuario=request.api_user,
            es_favorita=True
        ).exclude(tipo='tarjeta').first()

    fecha = parse_fecha_hora_input(data.get('fecha'))

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


@csrf_exempt
@api_auth_required
@require_http_methods(["POST"])
def editar_movimiento_api(request):
    """
    Edita cualquier movimiento del presupuesto (gasto, ingreso, transferencia,
    extraccion_tarjeta, aporte_efectivo, diferencia_tarjeta) y limpia el flag es_rapido.
    POST /api/movimientos/editar/
    """
    data = parse_request_data(request)
    tipo_mov = (data.get('tipo_movimiento') or '').strip().lower()
    mov_id = data.get('id')

    if not tipo_mov or not mov_id:
        return JsonResponse({'success': False, 'error': 'Faltan identificadores del movimiento'}, status=400)

    editables_ids = set(presupuestos_editables(request.api_user).values_list('id', flat=True))

    monto_raw = data.get('monto')
    monto = None
    if monto_raw is not None and str(monto_raw).strip() != '':
        try:
            monto = Decimal(str(monto_raw).replace(',', '.'))
            if monto <= 0:
                return JsonResponse({'success': False, 'error': 'El monto debe ser mayor a cero'}, status=400)
        except (InvalidOperation, TypeError):
            return JsonResponse({'success': False, 'error': 'Monto inválido'}, status=400)

    if tipo_mov == 'gasto':
        gasto = Gasto.objects.select_related('presupuesto').filter(id=mov_id, presupuesto_id__in=editables_ids).first()
        if not gasto:
            return JsonResponse({'success': False, 'error': 'Gasto no encontrado'}, status=404)

        if monto is not None:
            gasto.monto = monto

        nombre = (data.get('nombre') or '').strip()
        if nombre:
            if nombre.startswith('⚡'):
                stripped = nombre.lstrip('⚡').strip()
                if stripped and not stripped.lower().startswith('gasto rápido') and not stripped.lower().startswith('gasto rapido'):
                    nombre = stripped
            gasto.nombre = nombre[:120]

        metodo_pago = (data.get('metodo_pago') or gasto.metodo_pago).strip().lower()
        if metodo_pago in ['efectivo', 'transferencia', 'tarjeta']:
            gasto.metodo_pago = metodo_pago

        if 'categoria_nombre' in data or 'categoria_id' in data:
            cat_id = data.get('categoria_id')
            cat_nom = (data.get('categoria_nombre') or '').strip()
            gasto.categoria = resolve_or_create_categoria(cat_id, cat_nom)

        if 'persona' in data:
            persona_raw = (data.get('persona') or '').strip()
            if persona_raw:
                parts = [p.strip().title() for p in persona_raw.split(',') if p.strip()]
                seen = []
                for p in parts:
                    if p not in seen:
                        seen.append(p)
                gasto.persona = ', '.join(seen)
            else:
                gasto.persona = ''

        if 'cuenta_bancaria' in data or gasto.metodo_pago == 'efectivo':
            cuenta_raw = (data.get('cuenta_bancaria') or '').strip()
            if gasto.metodo_pago == 'efectivo' or not cuenta_raw or cuenta_raw.lower() == 'efectivo':
                gasto.cuenta_bancaria = None
            else:
                cuenta_obj = CuentaBancaria.objects.filter(
                    usuario=request.api_user,
                    nombre__iexact=cuenta_raw
                ).first()
                if not cuenta_obj:
                    cuenta_obj = CuentaBancaria.objects.create(
                        usuario=request.api_user,
                        nombre=cuenta_raw.title(),
                        tipo='tarjeta' if gasto.metodo_pago == 'tarjeta' else 'billetera'
                    )
                gasto.cuenta_bancaria = cuenta_obj

        if 'descripcion' in data:
            gasto.descripcion = (data.get('descripcion') or '').strip() or None

        nueva_fecha = parse_fecha_hora_input(data.get('fecha'))
        if nueva_fecha:
            gasto.fecha = nueva_fecha

        gasto.es_rapido = False
        gasto.full_clean()
        gasto.save()

        # Si pertenece a una compra en cuotas, mantener alineadas la fecha base y tarjeta en las demás cuotas
        if gasto.grupo_cuotas_uid and (nueva_fecha or 'cuenta_bancaria' in data):
            k_cur = max(1, gasto.cuota_actual or 1)
            dt_base_compra = add_months_datetime(get_local_dt(gasto.fecha), -(k_cur - 1))
            hermanas = Gasto.objects.filter(
                presupuesto=gasto.presupuesto,
                grupo_cuotas_uid=gasto.grupo_cuotas_uid
            ).exclude(id=gasto.id)
            for h in hermanas:
                changed_h = False
                if nueva_fecha:
                    k_h = max(1, h.cuota_actual or 1)
                    h.fecha = add_months_datetime(dt_base_compra, k_h - 1)
                    changed_h = True
                if 'cuenta_bancaria' in data:
                    h.cuenta_bancaria = gasto.cuenta_bancaria
                    changed_h = True
                if changed_h:
                    h.save(update_fields=['fecha', 'cuenta_bancaria', 'fecha_actualizacion'])

        gasto.presupuesto.actualizar_monto_restante()
        return JsonResponse({'success': True, 'mensaje': 'Gasto actualizado correctamente'})

    elif tipo_mov in ['ingreso', 'extraccion_tarjeta', 'aporte_efectivo']:
        ingreso = Ingreso.objects.select_related('presupuesto').filter(id=mov_id, presupuesto_id__in=editables_ids).first()
        if not ingreso:
            return JsonResponse({'success': False, 'error': 'Ingreso no encontrado'}, status=404)

        if monto is not None:
            ingreso.monto = monto

        nombre = (data.get('nombre') or '').strip()
        if nombre:
            if nombre.startswith('⚡'):
                stripped = nombre.lstrip('⚡').strip()
                if stripped and not stripped.lower().startswith('ingreso rápido') and not stripped.lower().startswith('ingreso rapido'):
                    nombre = stripped
            ingreso.nombre = nombre[:120]

        if tipo_mov == 'extraccion_tarjeta':
            tarjeta_id = data.get('tarjeta_id')
            if tarjeta_id:
                tarjeta = ingreso.presupuesto.tarjetas_prestamo.filter(id=tarjeta_id).first()
                if tarjeta:
                    ingreso.tarjeta_prestamo = tarjeta
            tasa_raw = data.get('tasa_interes')
            if tasa_raw not in [None, '']:
                try:
                    ingreso.tasa_interes = Decimal(str(tasa_raw).replace(',', '.'))
                except (InvalidOperation, TypeError):
                    pass
            prox_raw = data.get('monto_proximo_mes')
            if prox_raw not in [None, '']:
                try:
                    ingreso.monto_proximo_mes = Decimal(str(prox_raw).replace(',', '.'))
                except (InvalidOperation, TypeError):
                    pass
            else:
                tasa_val = ingreso.tasa_interes or Decimal('4.50')
                ingreso.monto_proximo_mes = round(ingreso.monto * (Decimal('1') + tasa_val / Decimal('100')), 2)
        elif tipo_mov == 'aporte_efectivo':
            ingreso.tipo_ingreso = 'efectivo'
            ingreso.cuenta_bancaria = None
        else:
            tipo_ing = (data.get('tipo_ingreso') or ingreso.tipo_ingreso).strip().lower()
            if tipo_ing in ['transferencia', 'efectivo', 'sueldo']:
                ingreso.tipo_ingreso = tipo_ing

            if 'cuenta_bancaria' in data or ingreso.tipo_ingreso == 'efectivo':
                cuenta_raw = (data.get('cuenta_bancaria') or '').strip()
                if ingreso.tipo_ingreso == 'efectivo' or not cuenta_raw or cuenta_raw.lower() == 'efectivo':
                    ingreso.cuenta_bancaria = None
                else:
                    cuenta_obj = CuentaBancaria.objects.filter(
                        usuario=request.api_user,
                        nombre__iexact=cuenta_raw
                    ).first()
                    if not cuenta_obj:
                        cuenta_obj = CuentaBancaria.objects.create(
                            usuario=request.api_user,
                            nombre=cuenta_raw.title(),
                            tipo='billetera'
                        )
                    ingreso.cuenta_bancaria = cuenta_obj

        if 'descripcion' in data:
            ingreso.descripcion = (data.get('descripcion') or '').strip() or None

        nueva_fecha = parse_fecha_hora_input(data.get('fecha'))
        if nueva_fecha:
            ingreso.fecha = nueva_fecha

        ingreso.es_rapido = False
        ingreso.full_clean()
        ingreso.save()
        ingreso.presupuesto.actualizar_monto_restante()
        return JsonResponse({'success': True, 'mensaje': 'Ingreso actualizado correctamente'})

    elif tipo_mov == 'transferencia':
        trans = TransferenciaFondos.objects.select_related('presupuesto').filter(id=mov_id, presupuesto_id__in=editables_ids).first()
        if not trans:
            return JsonResponse({'success': False, 'error': 'Transferencia no encontrada'}, status=404)

        if monto is not None:
            trans.monto = monto

        origen_tipo = (data.get('origen_tipo') or trans.origen_tipo).strip().lower()
        destino_tipo = (data.get('destino_tipo') or trans.destino_tipo).strip().lower()
        if origen_tipo == 'efectivo' and destino_tipo == 'efectivo':
            return JsonResponse({'success': False, 'error': 'Origen y destino no pueden ser ambos Efectivo'}, status=400)

        trans.origen_tipo = origen_tipo if origen_tipo in ['efectivo', 'cuenta'] else 'efectivo'
        trans.destino_tipo = destino_tipo if destino_tipo in ['efectivo', 'cuenta'] else 'cuenta'

        if trans.origen_tipo == 'efectivo':
            trans.origen_cuenta = None
        elif 'origen_cuenta' in data:
            orig_raw = (data.get('origen_cuenta') or '').strip()
            if orig_raw:
                trans.origen_cuenta, _ = CuentaBancaria.objects.get_or_create(
                    usuario=request.api_user,
                    nombre__iexact=orig_raw,
                    defaults={'nombre': orig_raw.title()}
                )

        if trans.destino_tipo == 'efectivo':
            trans.destino_cuenta = None
        elif 'destino_cuenta' in data:
            dest_raw = (data.get('destino_cuenta') or '').strip()
            if dest_raw:
                trans.destino_cuenta, _ = CuentaBancaria.objects.get_or_create(
                    usuario=request.api_user,
                    nombre__iexact=dest_raw,
                    defaults={'nombre': dest_raw.title()}
                )

        if 'nota' in data:
            trans.nota = (data.get('nota') or '').strip()[:200]

        trans.full_clean()
        trans.save()
        return JsonResponse({'success': True, 'mensaje': 'Transferencia actualizada correctamente'})

    elif tipo_mov == 'diferencia_tarjeta':
        diff = DiferenciaTarjeta.objects.select_related('ciclo_prestamo__presupuesto').filter(
            id=mov_id,
            ciclo_prestamo__presupuesto_id__in=editables_ids
        ).first()
        if not diff:
            return JsonResponse({'success': False, 'error': 'Diferencia no encontrada'}, status=404)

        if monto is not None:
            diff.monto = monto
        if 'concepto' in data:
            concepto = (data.get('concepto') or '').strip()
            if concepto:
                diff.concepto = concepto[:150]
        tarjeta_id = data.get('tarjeta_id')
        if tarjeta_id:
            tarjeta = diff.ciclo_prestamo.presupuesto.tarjetas_prestamo.filter(id=tarjeta_id).first()
            if tarjeta:
                diff.tarjeta = tarjeta
        diff.save()
        return JsonResponse({'success': True, 'mensaje': 'Diferencia actualizada correctamente'})

    return JsonResponse({'success': False, 'error': 'Tipo de movimiento no soportado'}, status=400)


@csrf_exempt
@api_auth_required
@require_http_methods(["POST"])
def eliminar_movimiento_api(request):
    """
    Elimina un movimiento del presupuesto (gasto, ingreso, transferencia,
    extraccion_tarjeta, aporte_efectivo, diferencia_tarjeta).
    POST /api/movimientos/eliminar/
    """
    data = parse_request_data(request)
    tipo_mov = (data.get('tipo_movimiento') or '').strip().lower()
    mov_id = data.get('id')

    if not tipo_mov or not mov_id:
        return JsonResponse({'success': False, 'error': 'Faltan identificadores del movimiento'}, status=400)

    editables_ids = set(presupuestos_editables(request.api_user).values_list('id', flat=True))

    if tipo_mov == 'gasto':
        gasto = Gasto.objects.select_related('presupuesto').filter(id=mov_id, presupuesto_id__in=editables_ids).first()
        if not gasto:
            return JsonResponse({'success': False, 'error': 'Gasto no encontrado'}, status=404)
        pres = gasto.presupuesto
        gasto.delete()
        pres.actualizar_monto_restante()
        return JsonResponse({'success': True, 'mensaje': 'Gasto eliminado'})

    elif tipo_mov in ['ingreso', 'extraccion_tarjeta', 'aporte_efectivo']:
        ingreso = Ingreso.objects.select_related('presupuesto').filter(id=mov_id, presupuesto_id__in=editables_ids).first()
        if not ingreso:
            return JsonResponse({'success': False, 'error': 'Ingreso no encontrado'}, status=404)
        pres = ingreso.presupuesto
        ingreso.delete()
        pres.actualizar_monto_restante()
        return JsonResponse({'success': True, 'mensaje': 'Ingreso eliminado'})

    elif tipo_mov == 'transferencia':
        trans = TransferenciaFondos.objects.filter(id=mov_id, presupuesto_id__in=editables_ids).first()
        if not trans:
            return JsonResponse({'success': False, 'error': 'Transferencia no encontrada'}, status=404)
        trans.delete()
        return JsonResponse({'success': True, 'mensaje': 'Transferencia eliminada'})

    elif tipo_mov == 'diferencia_tarjeta':
        diff = DiferenciaTarjeta.objects.filter(
            id=mov_id,
            ciclo_prestamo__presupuesto_id__in=editables_ids
        ).first()
        if not diff:
            return JsonResponse({'success': False, 'error': 'Diferencia no encontrada'}, status=404)
        diff.delete()
        return JsonResponse({'success': True, 'mensaje': 'Diferencia eliminada'})

    return JsonResponse({'success': False, 'error': 'Tipo de movimiento no soportado'}, status=400)


@csrf_exempt
@api_auth_required
@require_http_methods(["POST"])
def pagar_resumen_tarjeta_api(request):
    """
    Permite:
    1) Agregar una diferencia por impuestos / sellos / mantenimiento al resumen de una tarjeta ('accion': 'solo_diferencia')
    2) O registrar el Pago del resumen de una tarjeta ('accion': 'pagar'), descontándolo de Efectivo o Transferencia/Billetera,
       incluyendo opcionalmente la diferencia de impuestos/sellos.
    POST /api/tarjetas/pagar-resumen/
    """
    data = parse_request_data(request)
    presupuesto_id = data.get('presupuesto_id')
    tarjeta_nombre = (data.get('tarjeta_nombre') or '').strip()
    accion = (data.get('accion') or 'pagar').strip().lower()  # 'pagar' | 'solo_diferencia'
    mes_resumen = (data.get('mes_resumen') or '').strip()

    if not presupuesto_id or not tarjeta_nombre:
        return JsonResponse({'success': False, 'error': 'Faltan datos de presupuesto o tarjeta'}, status=400)

    presupuesto = presupuestos_editables(request.api_user).filter(id=presupuesto_id).first()
    if not presupuesto:
        return JsonResponse({'success': False, 'error': 'Presupuesto no encontrado'}, status=404)

    tarjeta_obj = CuentaBancaria.objects.filter(
        usuario=request.api_user,
        nombre__iexact=tarjeta_nombre
    ).first()
    if not tarjeta_obj:
        tarjeta_obj = CuentaBancaria.objects.create(
            usuario=request.api_user,
            nombre=tarjeta_nombre[:60],
            tipo='tarjeta'
        )

    dif_raw = data.get('monto_diferencia')
    monto_diferencia = Decimal('0')
    if dif_raw not in [None, '', '0', 0]:
        try:
            monto_diferencia = max(Decimal('0'), Decimal(str(dif_raw).replace(',', '.')))
        except (InvalidOperation, TypeError):
            return JsonResponse({'success': False, 'error': 'Monto de diferencia inválido'}, status=400)

    concepto_dif = (data.get('concepto_diferencia') or 'Impuestos y mantenimiento resumen').strip()
    fecha_pago = parse_fecha_hora_input(data.get('fecha')) or timezone.localtime(timezone.now())

    # Si solo quiere agregar la diferencia/impuestos al resumen de la tarjeta:
    if accion == 'solo_diferencia':
        if monto_diferencia <= 0:
            return JsonResponse({'success': False, 'error': 'Ingresá un monto de diferencia/impuestos mayor a 0'}, status=400)

        # Ubicar la fecha en el mes del resumen si se especificó YYYY-MM
        fecha_dif = fecha_pago
        if re.match(r'^\d{4}-\d{2}$', mes_resumen) and get_local_ym(fecha_pago) != mes_resumen:
            y_r, m_r = [int(x) for x in mes_resumen.split('-')]
            last_d = calendar.monthrange(y_r, m_r)[1]
            fecha_dif = timezone.make_aware(
                datetime(y_r, m_r, min(fecha_pago.day, last_d), 12, 0),
                timezone.get_current_timezone()
            )

        cat_tarj = resolve_or_create_categoria(None, 'Tarjeta de crédito')
        g_dif = Gasto.objects.create(
            presupuesto=presupuesto,
            categoria=cat_tarj,
            nombre=f"{concepto_dif} · {tarjeta_obj.nombre}"[:100],
            cuenta_bancaria=tarjeta_obj,
            monto=monto_diferencia,
            metodo_pago='tarjeta',
            fecha=fecha_dif,
            es_rapido=False,
            es_ajuste_tarjeta=True,
        )
        return JsonResponse({
            'success': True,
            'mensaje': f'Diferencia de ${monto_diferencia:,.0f} sumada al resumen de {tarjeta_obj.nombre}',
            'gasto_id': g_dif.id,
        }, status=201)

    # Acción 'pagar': Registrar el pago real de la tarjeta (descuenta de Efectivo o Transferencia)
    monto_pagar_raw = data.get('monto_total')
    try:
        monto_total = Decimal(str(monto_pagar_raw).replace(',', '.'))
        if monto_total <= 0:
            return JsonResponse({'success': False, 'error': 'El monto total a pagar debe ser mayor a cero'}, status=400)
    except (InvalidOperation, TypeError):
        return JsonResponse({'success': False, 'error': 'Monto a pagar inválido'}, status=400)

    # Si además ingresó una diferencia de impuestos que aún no estaba cargada en la tarjeta, registrarla en el resumen de la tarjeta
    if monto_diferencia > 0 and bool(data.get('registrar_diferencia_en_tarjeta', True)):
        fecha_dif = fecha_pago
        if re.match(r'^\d{4}-\d{2}$', mes_resumen) and get_local_ym(fecha_pago) != mes_resumen:
            y_r, m_r = [int(x) for x in mes_resumen.split('-')]
            last_d = calendar.monthrange(y_r, m_r)[1]
            fecha_dif = timezone.make_aware(
                datetime(y_r, m_r, min(fecha_pago.day, last_d), 12, 0),
                timezone.get_current_timezone()
            )
        cat_tarj = resolve_or_create_categoria(None, 'Tarjeta de crédito')
        Gasto.objects.create(
            presupuesto=presupuesto,
            categoria=cat_tarj,
            nombre=f"{concepto_dif} · {tarjeta_obj.nombre}"[:100],
            cuenta_bancaria=tarjeta_obj,
            monto=monto_diferencia,
            metodo_pago='tarjeta',
            fecha=fecha_dif,
            es_rapido=False,
            es_ajuste_tarjeta=True,
        )

    metodo_pago = (data.get('metodo_pago') or 'transferencia').strip().lower()
    if metodo_pago not in ['efectivo', 'transferencia']:
        metodo_pago = 'transferencia'

    cuenta_origen_raw = (data.get('cuenta_bancaria') or '').strip()
    cuenta_origen = None
    if metodo_pago == 'transferencia':
        if cuenta_origen_raw:
            cuenta_origen = CuentaBancaria.objects.filter(
                usuario=request.api_user,
                nombre__iexact=cuenta_origen_raw
            ).first()
        if not cuenta_origen:
            cuenta_origen = CuentaBancaria.objects.filter(
                usuario=request.api_user,
                es_favorita=True
            ).exclude(tipo='tarjeta').first()

    mes_label_str = format_mes_label(mes_resumen) if mes_resumen else ''
    target_ym = mes_resumen if re.match(r'^\d{4}-\d{2}$', mes_resumen) else get_local_ym(fecha_pago)
    all_tarj_gastos = list(
        presupuesto.gastos.select_related('cuenta_bancaria').filter(
            metodo_pago='tarjeta',
            cuenta_bancaria=tarjeta_obj,
            es_ajuste_tarjeta=False,
        )
    )
    c1_map = {}
    for x in all_tarj_gastos:
        if x.grupo_cuotas_uid:
            prev_x = c1_map.get(x.grupo_cuotas_uid)
            if prev_x is None or (x.cuota_actual or 1) < (prev_x.cuota_actual or 1):
                c1_map[x.grupo_cuotas_uid] = x
    consumos_periodo = [
        x for x in all_tarj_gastos
        if calcular_imputacion_tarjeta(x, c_obj=tarjeta_obj, cuota1_map=c1_map)['mes_resumen_ym'] == target_ym
    ]
    subtotal_consumos = sum((x.monto for x in consumos_periodo), Decimal('0'))
    diferencia_calc = monto_total - subtotal_consumos

    nombre_pago = f"Pago tarjeta {tarjeta_obj.nombre}" + (f" ({mes_label_str})" if mes_label_str else "")
    cat_pago = resolve_or_create_categoria(None, 'Tarjeta de crédito')
    desc_pago = f"Pago de resumen de {tarjeta_obj.nombre} [Periodo:{target_ym}] · Consumos registrados: ${subtotal_consumos:,.0f} · Diferencia: ${diferencia_calc:,.0f}"
    if monto_diferencia > 0:
        desc_pago += f" ({concepto_dif})"

    gasto_pago = Gasto.objects.create(
        presupuesto=presupuesto,
        categoria=cat_pago,
        nombre=nombre_pago[:100],
        cuenta_bancaria=cuenta_origen,
        monto=monto_total,
        metodo_pago=metodo_pago,
        descripcion=desc_pago,
        fecha=fecha_pago,
        es_rapido=False,
    )
    presupuesto.refresh_from_db()

    return JsonResponse({
        'success': True,
        'mensaje': f'Pago de {tarjeta_obj.nombre} por ${monto_total:,.0f} registrado',
        'gasto_id': gasto_pago.id,
        'subtotal_consumos': float(subtotal_consumos),
        'diferencia': float(diferencia_calc),
    }, status=201)



