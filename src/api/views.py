import json
from decimal import Decimal, InvalidOperation
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date
from django.db.models import Q

from presupuestos.models import Presupuesto, Categoria, Gasto, Ingreso
from presupuestos.views import presupuestos_editables, presupuestos_visibles
from .models import ApiToken
from .auth import api_auth_required, get_user_from_request


def parse_request_data(request):
    """Obtiene los datos tanto si vienen en JSON como en form-data."""
    if request.content_type and 'application/json' in request.content_type:
        try:
            return json.loads(request.body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return {}
    return request.POST.dict()


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
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
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
        'username': user.username
    })


@api_auth_required
@require_http_methods(["GET"])
def presupuestos_api(request):
    """
    Lista todos los presupuestos en los que el usuario puede cargar gastos.
    GET /api/presupuestos/
    """
    presupuestos = presupuestos_editables(request.api_user).order_by('-fecha_inicio')
    hoy = timezone.localdate()

    items = []
    for p in presupuestos:
        es_activo = (p.fecha_inicio <= hoy <= p.fecha_fin)
        items.append({
            'id': p.id,
            'nombre': p.nombre,
            'descripcion': p.descripcion or '',
            'moneda': p.moneda,
            'moneda_display': p.get_moneda_display(),
            'fecha_inicio': p.fecha_inicio.strftime('%Y-%m-%d'),
            'fecha_fin': p.fecha_fin.strftime('%Y-%m-%d'),
            'monto_total': float(p.monto_total),
            'monto_restante': float(p.monto_restante),
            'total_ingresos': float(p.total_ingresos),
            'disponible': float(p.monto_total + p.total_ingresos),
            'porcentaje_gastado': round(float(p.porcentaje_gastado()), 1),
            'gastos_count': p.gastos.count(),
            'es_activo': es_activo,
            'es_propio': p.usuario_id == request.api_user.id,
        })

    return JsonResponse({
        'success': True,
        'presupuestos': items
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
    Body:
    {
        "presupuesto_id": 1,
        "nombre": "Almuerzo",
        "monto": 2500.50,
        "categoria_id": 2, // opcional
        "descripcion": "", // opcional
        "fecha": "2026-11-05 10:30:00" // opcional
    }
    """
    data = parse_request_data(request)
    presupuesto_id = data.get('presupuesto_id')
    nombre = (data.get('nombre') or '').strip()
    monto_raw = data.get('monto')

    if not presupuesto_id:
        return JsonResponse({'success': False, 'error': 'Falta el presupuesto_id'}, status=400)
    if not nombre:
        return JsonResponse({'success': False, 'error': 'El nombre del gasto es obligatorio'}, status=400)
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

    # Categoría opcional
    categoria = None
    categoria_id = data.get('categoria_id')
    if categoria_id:
        categoria = Categoria.objects.filter(id=categoria_id).first()

    # Fecha opcional
    fecha = None
    fecha_raw = data.get('fecha')
    if fecha_raw:
        fecha = parse_datetime(fecha_raw) or parse_date(fecha_raw)

    descripcion = (data.get('descripcion') or '').strip()
    metodo_pago = (data.get('metodo_pago') or 'efectivo').lower().strip()
    if metodo_pago not in ['efectivo', 'transferencia', 'tarjeta']:
        metodo_pago = 'efectivo'

    gasto = Gasto(
        presupuesto=presupuesto,
        categoria=categoria,
        nombre=nombre,
        monto=monto,
        metodo_pago=metodo_pago,
        descripcion=descripcion or None,
        fecha=fecha or timezone.localtime(timezone.now())
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
    Body:
    {
        "presupuesto_id": 1,
        "nombre": "Sueldo",
        "monto": 50000.00,
        "descripcion": "" // opcional
    }
    """
    data = parse_request_data(request)
    presupuesto_id = data.get('presupuesto_id')
    nombre = (data.get('nombre') or '').strip()
    monto_raw = data.get('monto')

    if not presupuesto_id or not nombre or monto_raw is None:
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

    tipo_ingreso = (data.get('tipo_ingreso') or 'transferencia').lower().strip()
    if tipo_ingreso not in ['transferencia', 'efectivo', 'sueldo']:
        tipo_ingreso = 'transferencia'

    ingreso = Ingreso(
        presupuesto=presupuesto,
        nombre=nombre,
        monto=monto,
        tipo_ingreso=tipo_ingreso,
        descripcion=data.get('descripcion') or None
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
    presupuestos_qs = presupuestos_editables(request.api_user).order_by('-fecha_inicio')
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
