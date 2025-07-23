from django import template

register = template.Library()

@register.filter
def sumar_montos(gastos):
    """
    Filtro personalizado para sumar los montos de una lista de gastos.
    """
    return sum(gasto.monto for gasto in gastos if hasattr(gasto, 'monto'))
