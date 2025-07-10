from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from django.views.decorators.http import require_POST
from .models import CalculadoraDivisa
from .forms import CalculadoraDivisaForm, ConversionForm
from django.utils import timezone

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
    
    return render(request, 'calculadoras/calcular_divisa.html', {
        'form': form,
        'calculadoras': calculadoras,
        'calculadora': calculadora,
        'resultado': resultado,
        'titulo': 'Nueva Conversión de Divisas'
    })
