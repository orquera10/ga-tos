from django.contrib import admin
from core.admin_mixins import JsonBackupAdminMixin
from .models import CalculadoraDivisa, HistorialConversion


@admin.register(CalculadoraDivisa)
class CalculadoraDivisaAdmin(JsonBackupAdminMixin, admin.ModelAdmin):
    list_display = ('nombre', 'moneda_origen', 'moneda_destino', 'relacion', 'fecha_creacion', 'fecha_actualizacion')
    list_filter = ('moneda_origen', 'moneda_destino', 'fecha_creacion')
    search_fields = ('nombre', 'moneda_origen', 'moneda_destino')
    date_hierarchy = 'fecha_creacion'
    ordering = ('-fecha_creacion',)


@admin.register(HistorialConversion)
class HistorialConversionAdmin(JsonBackupAdminMixin, admin.ModelAdmin):
    list_display = ('calculadora', 'monto_origen', 'moneda_origen', 'monto_destino', 'moneda_destino', 'direccion', 'usuario', 'fecha_conversion')
    list_filter = ('direccion', 'moneda_origen', 'moneda_destino', 'fecha_conversion')
    search_fields = ('calculadora__nombre', 'usuario', 'ip_usuario')
    date_hierarchy = 'fecha_conversion'
    ordering = ('-fecha_conversion',)
    autocomplete_fields = ('calculadora',)
    readonly_fields = ('fecha_conversion', 'ip_usuario', 'user_agent')
