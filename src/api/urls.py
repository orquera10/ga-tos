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
    path('cuentas/crear/', views.crear_cuenta_api, name='crear_cuenta'),
    path('cuentas/<int:pk>/eliminar/', views.eliminar_cuenta_api, name='eliminar_cuenta'),

    # Vista ultra-rápida optimizada para el Widget
    path('widget/resumen/', views.widget_resumen_api, name='widget_resumen'),
]
