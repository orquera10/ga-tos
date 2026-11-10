from django.urls import path
from . import views

app_name = 'api'

urlpatterns = [
    # Autenticación y Tokens
    path('auth/login/', views.login_api, name='login'),
    path('auth/token/', views.mi_token_api, name='mi_token'),

    # Recursos para la App / Widget
    path('presupuestos/', views.presupuestos_api, name='presupuestos'),
    path('presupuestos/activo/detalle/', views.presupuesto_detalle_api, name='presupuesto_activo_detalle'),
    path('presupuestos/<int:pk>/detalle/', views.presupuesto_detalle_api, name='presupuesto_detalle'),
    path('categorias/', views.categorias_api, name='categorias'),
    path('metadata/', views.metadata_api, name='metadata'),

    # Acciones de carga rápida y gestión de cuentas / transferencias
    path('gastos/crear/', views.crear_gasto_api, name='crear_gasto'),
    path('ingresos/crear/', views.crear_ingreso_api, name='crear_ingreso'),
    path('transferencias/crear/', views.crear_transferencia_api, name='crear_transferencia'),
    path('movimientos/editar/', views.editar_movimiento_api, name='editar_movimiento'),
    path('movimientos/eliminar/', views.eliminar_movimiento_api, name='eliminar_movimiento'),
    path('cuentas/crear/', views.crear_cuenta_api, name='crear_cuenta'),
    path('cuentas/<int:pk>/eliminar/', views.eliminar_cuenta_api, name='eliminar_cuenta'),

    # Acciones específicas para presupuestos tipo Préstamo
    path('prestamo/ingreso/crear/', views.crear_ingreso_prestamo_api, name='crear_ingreso_prestamo'),
    path('prestamo/diferencia/crear/', views.crear_diferencia_prestamo_api, name='crear_diferencia_prestamo'),
    path('prestamo/tarjeta/guardar/', views.guardar_tarjeta_prestamo_api, name='guardar_tarjeta_prestamo'),
    path('prestamo/cerrar-ciclo/', views.cerrar_ciclo_prestamo_api, name='cerrar_ciclo_prestamo'),

    # Vista ultra-rápida optimizada para el Widget
    path('widget/resumen/', views.widget_resumen_api, name='widget_resumen'),
]
