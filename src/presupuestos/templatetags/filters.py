from django import template

register = template.Library()

@register.filter
def sumar_montos(registros):
    """
    Filtro personalizado para sumar los montos de una lista de gastos o ingresos.
    """
    return sum(registro.monto for registro in registros if hasattr(registro, 'monto'))

@register.filter
def model_name(obj):
    """
    Devuelve el nombre del modelo (en minúsculas) de un objeto.
    """
    try:
        return obj._meta.model_name
    except AttributeError:
        return ''

@register.filter
def select_model(iterable, model_name):
    """
    Filtra un iterable para incluir solo objetos del modelo especificado.
    """
    return [item for item in iterable if hasattr(item, '_meta') and item._meta.model_name == model_name.lower()]

@register.filter
def progress_bar_color(porcentaje):
    """
    Devuelve la clase de color de Bootstrap según el porcentaje de gasto.
    """
    try:
        val = float(porcentaje)
        if val < 50:
            return 'success'
        elif val < 75:
            return 'warning'
        else:
            return 'danger'
    except (ValueError, TypeError):
        return 'success'

@register.filter
def sub(value, arg):
    """
    Resta arg a value. Útil en plantillas.
    Ejemplo: {{ value|sub:arg }}
    """
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return ''

@register.filter
def es_transaccion_rapida(transaccion):
    """
    Determina si un gasto o ingreso fue cargado rápido y requiere completarse/editarse.
    Detecta si tiene flag es_rapido, 'rapido', 'rápido', '⚡' en el nombre, o si es un gasto sin categoría.
    """
    if not transaccion:
        return False
    if getattr(transaccion, 'es_rapido', False):
        return True
    nombre = str(getattr(transaccion, 'nombre', '') or '').lower()
    if any(k in nombre for k in ['rápido', 'rapido', '⚡', 'rapida', 'rápida']):
        return True
    if hasattr(transaccion, 'categoria') and transaccion.categoria is None:
        return True
    return False

