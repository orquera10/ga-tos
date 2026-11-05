import secrets
from django.db import models
from django.conf import settings
from django.utils import timezone


def generate_api_token():
    return secrets.token_hex(24)  # 48 caracteres hexadecimales


class ApiToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='api_tokens'
    )
    token = models.CharField(max_length=64, unique=True, default=generate_api_token, db_index=True)
    nombre = models.CharField(max_length=100, default='Android App / Widget')
    creado_el = models.DateTimeField(default=timezone.now)
    ultimo_uso = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Token de API'
        verbose_name_plural = 'Tokens de API'
        ordering = ['-creado_el']

    def __str__(self):
        return f"{self.user.username} - {self.nombre} ({self.token[:8]}...)"
