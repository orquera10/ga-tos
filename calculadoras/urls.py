from django.urls import path
from . import views
from . import api_views

app_name = 'calculadoras'

urlpatterns = [
    path('', views.index, name='index'),
    path('nueva/', views.crear_calculadora, name='crear_calculadora'),
    path('editar/<int:calculadora_id>/', views.editar_calculadora, name='editar_calculadora'),
    path('calcular/', views.calcular_divisa, name='calcular_divisa'),
    path('calcular/<int:calculadora_id>/', views.calcular_divisa, name='calcular_con_calculadora'),
    path('historial/<int:calculadora_id>/', views.historial_conversiones, name='historial_conversiones'),
    path('borrar/<int:calculadora_id>/', views.borrar_calculadora, name='borrar_calculadora'),
    # API endpoints
    path('api/calculadora/<int:calculadora_id>/', api_views.calculadora_detalle_api, name='calculadora_detalle_api'),
]
