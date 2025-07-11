from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from .models import CalculadoraDivisa

def calculadora_detalle_api(request, calculadora_id):
    try:
        calculadora = CalculadoraDivisa.objects.get(id=calculadora_id)
        return JsonResponse({
            'id': calculadora.id,
            'nombre': calculadora.nombre,
            'moneda_origen': calculadora.moneda_origen,
            'moneda_destino': calculadora.moneda_destino,
            'relacion': float(calculadora.relacion)
        })
    except CalculadoraDivisa.DoesNotExist:
        return JsonResponse({'error': 'Calculadora no encontrada'}, status=404)
