from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.auth import USUARIO_PRESUPUESTOS_EXISTENTES, asignar_presupuestos_sin_usuario


class Command(BaseCommand):
    help = 'Crea el usuario dario si falta y le asigna los presupuestos sin usuario.'

    def handle(self, *args, **options):
        User = get_user_model()
        usuario, creado = User.objects.get_or_create(
            username=USUARIO_PRESUPUESTOS_EXISTENTES,
            defaults={'is_staff': True, 'is_superuser': True},
        )
        if creado:
            usuario.set_unusable_password()
            usuario.save(update_fields=['password'])

        asignados = asignar_presupuestos_sin_usuario()
        estado = 'creado' if creado else 'existente'
        self.stdout.write(
            self.style.SUCCESS(
                f'Usuario {usuario.username} {estado}. Presupuestos asignados: {asignados}.'
            )
        )
