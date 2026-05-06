from django.contrib.auth import get_user_model


USUARIO_PRESUPUESTOS_EXISTENTES = 'dario'


def asignar_presupuestos_sin_usuario():
    from presupuestos.models import Presupuesto

    User = get_user_model()
    try:
        usuario = User.objects.get(username=USUARIO_PRESUPUESTOS_EXISTENTES)
    except User.DoesNotExist:
        return 0
    return Presupuesto.objects.filter(usuario__isnull=True).update(usuario=usuario)
