from django.urls import path
from . import views

app_name = 'api'

urlpatterns = [
    # Autenticación y Tokens
    path('auth/login/', views.login_api, name='login'),
    path('auth/token/', views.mi_token_api, name='mi_token'),

    # Recursos para la App / Widget
    path('presupuestos/', views.presupuestos_api, name='presupuestos'),
    path('categorias/', views.categorias_api, name='categorias'),

    # Acciones de carga rápida
    path('gastos/crear/', views.crear_gasto_api, name='crear_gasto'),
    path('ingresos/crear/', views.crear_ingreso_api, name='crear_ingreso'),

    # Vista ultra-rápida optimizada para el Widget
    path('widget/resumen/', views.widget_resumen_api, name='widget_resumen'),
]
