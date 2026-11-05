from django.contrib import admin
from .models import ApiToken


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'nombre', 'token_masked', 'creado_el', 'ultimo_uso')
    search_fields = ('user__username', 'user__email', 'nombre', 'token')
    list_filter = ('creado_el', 'ultimo_uso')
    readonly_fields = ('token', 'creado_el', 'ultimo_uso')

    def token_masked(self, obj):
        if obj.token:
            return f"{obj.token[:8]}...{obj.token[-4:]}"
        return "-"
    token_masked.short_description = 'Token'
