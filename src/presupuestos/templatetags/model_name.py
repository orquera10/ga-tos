from django import template

register = template.Library()

@register.filter
def model_name(obj):
    """
    Returns the model name (lowercase) of an object.
    """
    try:
        return obj._meta.model_name
    except AttributeError:
        return ''

@register.filter
def select_model(iterable, model_name):
    """
    Filters an iterable to include only objects of the specified model.
    """
    return [item for item in iterable if hasattr(item, '_meta') and item._meta.model_name == model_name.lower()]
