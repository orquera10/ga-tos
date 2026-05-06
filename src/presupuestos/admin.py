from django.contrib import admin
from core.admin_mixins import JsonBackupAdminMixin
from .models import Categoria, Gasto, Ingreso, Presupuesto, PresupuestoCompartido


class GastoInline(admin.TabularInline):
    model = Gasto
    extra = 0
    fields = ('nombre', 'categoria', 'monto', 'fecha')
    readonly_fields = ()


class IngresoInline(admin.TabularInline):
    model = Ingreso
    extra = 0
    fields = ('nombre', 'monto', 'fecha')


class PresupuestoCompartidoInline(admin.TabularInline):
    model = PresupuestoCompartido
    extra = 0
    autocomplete_fields = ('usuario',)


@admin.register(Presupuesto)
class PresupuestoAdmin(JsonBackupAdminMixin, admin.ModelAdmin):
    list_display = ('nombre', 'usuario', 'monto_total', 'monto_restante', 'moneda', 'fecha_inicio', 'fecha_fin', 'fecha_creacion')
    list_filter = ('moneda', 'usuario', 'fecha_inicio', 'fecha_fin', 'fecha_creacion')
    search_fields = ('nombre', 'descripcion', 'usuario__username', 'usuario__email')
    date_hierarchy = 'fecha_creacion'
    ordering = ('-fecha_creacion',)
    inlines = (PresupuestoCompartidoInline, GastoInline, IngresoInline)


@admin.register(Gasto)
class GastoAdmin(JsonBackupAdminMixin, admin.ModelAdmin):
    list_display = ('nombre', 'presupuesto', 'categoria', 'monto', 'fecha', 'usuario_presupuesto')
    list_filter = ('categoria', 'fecha', 'presupuesto__usuario')
    search_fields = ('nombre', 'descripcion', 'presupuesto__nombre', 'presupuesto__usuario__username')
    date_hierarchy = 'fecha'
    ordering = ('-fecha',)
    autocomplete_fields = ('presupuesto', 'categoria')

    @admin.display(description='Usuario')
    def usuario_presupuesto(self, obj):
        return obj.presupuesto.usuario


@admin.register(Ingreso)
class IngresoAdmin(JsonBackupAdminMixin, admin.ModelAdmin):
    list_display = ('nombre', 'presupuesto', 'monto', 'fecha', 'usuario_presupuesto')
    list_filter = ('fecha', 'presupuesto__usuario')
    search_fields = ('nombre', 'descripcion', 'presupuesto__nombre', 'presupuesto__usuario__username')
    date_hierarchy = 'fecha'
    ordering = ('-fecha',)
    autocomplete_fields = ('presupuesto',)

    @admin.display(description='Usuario')
    def usuario_presupuesto(self, obj):
        return obj.presupuesto.usuario


@admin.register(Categoria)
class CategoriaAdmin(JsonBackupAdminMixin, admin.ModelAdmin):
    list_display = ('nombre', 'descripcion')
    search_fields = ('nombre', 'descripcion')


@admin.register(PresupuestoCompartido)
class PresupuestoCompartidoAdmin(JsonBackupAdminMixin, admin.ModelAdmin):
    list_display = ('presupuesto', 'usuario', 'permiso', 'fecha_creacion')
    list_filter = ('permiso', 'fecha_creacion')
    search_fields = ('presupuesto__nombre', 'usuario__username', 'usuario__email')
    autocomplete_fields = ('presupuesto', 'usuario')
