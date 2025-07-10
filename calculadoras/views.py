from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import transaction
from .models import CalculadoraDivisa, HistorialConversion
from .forms import CalculadoraDivisaForm, ConversionForm

def get_client_ip(request):
    """Obtiene la IP del cliente"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def index(request):
    calculadoras = CalculadoraDivisa.objects.all().order_by('-fecha_creacion')
    context = {
        'calculadoras': calculadoras,
        'titulo': 'Calculadoras de Divisas'
    }
    return render(request, 'calculadoras/index.html', context)

def borrar_calculadora(request, calculadora_id):
    calculadora = get_object_or_404(CalculadoraDivisa, id=calculadora_id)
    
    if request.method == 'POST':
        nombre_calculadora = calculadora.nombre
        calculadora.delete()
        messages.success(request, f'Calculadora "{nombre_calculadora}" eliminada correctamente.')
        return redirect('calculadoras:index')
        
    return render(request, 'calculadoras/calculadora_confirm_delete.html', {'object': calculadora})

def crear_calculadora(request):
    if request.method == 'POST':
        form = CalculadoraDivisaForm(request.POST)
        if form.is_valid():
            try:
                calculadora = form.save()
                messages.success(request, f'Calculadora creada exitosamente: {calculadora.nombre}')
                return redirect('calculadoras:index')
            except Exception as e:
                messages.error(request, f'Error al guardar la calculadora: {str(e)}')
        else:
            messages.error(request, 'Por favor, verifica los datos ingresados')
    else:
        form = CalculadoraDivisaForm()
    
    return render(request, 'calculadoras/crear_calculadora.html', {
        'form': form,
        'titulo': 'Nueva Calculadora de Divisas'
    })

def calcular_divisa(request, calculadora_id=None):
    calculadora = None
    resultado = None
    direccion = request.POST.get('direccion', 'directa')
    calculadoras = CalculadoraDivisa.objects.all().order_by('-fecha_creacion')
    
    if calculadora_id:
        calculadora = get_object_or_404(CalculadoraDivisa, id=calculadora_id)
    
    if request.method == 'POST':
        form = ConversionForm(request.POST, calculadora=calculadora)
        if form.is_valid():
            calculadora = form.cleaned_data['calculadora']
            monto = form.cleaned_data['monto']
            
            # Determinar si es conversión directa o inversa
            es_conversion_inversa = (direccion == 'inversa')
            
            if es_conversion_inversa:
                monto_convertido = calculadora.convertir(monto, direccion='inversa')
                moneda_origen = calculadora.moneda_destino
                moneda_destino = calculadora.moneda_origen
                relacion = 1 / float(calculadora.relacion)
            else:
                monto_convertido = calculadora.convertir(monto, direccion='directa')
                moneda_origen = calculadora.moneda_origen
                moneda_destino = calculadora.moneda_destino
                relacion = calculadora.relacion
            
            # Obtener la fecha/hora actual con la zona horaria configurada
            fecha_actual = timezone.localtime(timezone.now())
            
            # Crear el registro de historial
            with transaction.atomic():
                HistorialConversion.objects.create(
                    calculadora=calculadora,
                    monto_origen=monto,
                    moneda_origen=moneda_origen,
                    monto_destino=monto_convertido,
                    moneda_destino=moneda_destino,
                    relacion_conversion=relacion,
                    direccion='inversa' if es_conversion_inversa else 'directa',
                    ip_usuario=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],  # Limitamos la longitud
                    usuario='Anónimo'  # Valor por defecto ya que no hay autenticación
                )
            
            resultado = {
                'monto_original': float(monto),
                'moneda_origen': moneda_origen,
                'monto_convertido': monto_convertido,
                'moneda_destino': moneda_destino,
                'fecha': fecha_actual,
                'relacion': relacion,
                'es_inversa': es_conversion_inversa
            }
    else:
        form = ConversionForm(calculadora=calculadora)
    
    # Preparar el contexto base
    context = {
        'form': form,
        'calculadoras': calculadoras,
        'calculadora': calculadora,
        'resultado': resultado,
        'titulo': 'Nueva Conversión de Divisas'
    }
    
    # Si hay una calculadora, agregar las últimas conversiones al contexto
    if calculadora:
        context['conversiones_recientes'] = HistorialConversion.objects.filter(
            calculadora=calculadora
        ).order_by('-fecha_conversion')[:5]
    
    return render(request, 'calculadoras/calcular_divisa.html', context)


def historial_conversiones(request, calculadora_id):
    """Muestra el historial de conversiones para una calculadora específica"""
    calculadora = get_object_or_404(CalculadoraDivisa, id=calculadora_id)
    
    # Obtener las últimas 50 conversiones para esta calculadora
    conversiones = HistorialConversion.objects.filter(
        calculadora=calculadora
    ).select_related('calculadora').order_by('-fecha_conversion')[:50]
    
    # Estadísticas básicas
    total_conversiones = conversiones.count()
    
    # Agrupar por día para el gráfico
    from django.db.models.functions import TruncDay
    from django.db.models import Count, Sum
    
    conversiones_por_dia = (
        HistorialConversion.objects
        .filter(calculadora=calculadora)
        .annotate(dia=TruncDay('fecha_conversion'))
        .values('dia')
        .annotate(total=Count('id'))
        .order_by('dia')
    )
    
    # Preparar datos para el gráfico
    dias = [c['dia'].strftime('%d/%m') for c in conversiones_por_dia]
    totales = [c['total'] for c in conversiones_por_dia]
    
    return render(request, 'calculadoras/historial_conversiones.html', {
        'calculadora': calculadora,
        'conversiones': conversiones,
        'total_conversiones': total_conversiones,
        'dias': dias,
        'totales': totales,
        'titulo': f'Historial de Conversiones - {calculadora.nombre}'
    })
